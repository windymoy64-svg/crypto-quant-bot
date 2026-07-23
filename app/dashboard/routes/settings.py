"""Dashboard REST endpoints for the Settings panel.

Manages exchange API credentials (Binance, Bitunix, ...) stored in the
encrypted secrets store. Values are never echoed back in plaintext; only a
masked hint of the API key is returned so operators can confirm what is
stored.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.settings.exchange_credentials import (
    DEFAULT_EXCHANGE,
    SUPPORTED_EXCHANGES,
    clear_exchange_credentials,
    load_exchange_credentials,
    mask_secret,
    save_exchange_credentials,
)
from app.settings.portfolio_preferences import (
    load_portfolio_preferences,
    save_portfolio_preferences,
)
from app.settings.execution_preferences import (
    LIVE_CONFIRMATION,
    kill_switch,
    load_execution_preferences,
    save_execution_preferences,
)
from app.settings.trading_preferences import (
    leverage_options,
    load_trading_preferences,
    save_trading_preferences,
)
from app.settings.llm_preferences import (
    AGENTS as LLM_AGENTS,
    clear_llm_provider,
    load_llm_api_key,
    load_llm_preferences,
    save_agent_models,
    save_llm_models,
    save_llm_provider,
)
from app.llm.client import LLMClientConfig, OpenAICompatibleClient


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["settings"])

BINANCE_MAINNET = "https://api.binance.com"
BINANCE_TESTNET = "https://testnet.binance.vision"
BITUNIX_FUTURES_BASE = "https://fapi.bitunix.com"
# Bitunix' edge is fronted by Cloudflare, which returns HTTP 403 with
# ``error code: 1010`` (banned browser signature) for the default
# ``Python-urllib/X.Y`` User-Agent. Any plausible UA passes the check.
BITUNIX_USER_AGENT = "crypto-quant-bot/1.0 (+dashboard)"


def _invalidate_multi_portfolio_cache() -> None:
    """Buang cache /api/portfolio/multi setelah preferensi/kredensial berubah.

    Lazy import dipakai untuk menghindari circular import: modul
    ``multi_portfolio`` sendiri mengimport helper dari modul ini.
    """

    try:
        from app.dashboard.routes.multi_portfolio import (
            invalidate_multi_portfolio_cache,
        )
    except Exception:  # pragma: no cover - defensive
        return
    try:
        invalidate_multi_portfolio_cache()
    except Exception:  # pragma: no cover - defensive
        logger.exception("Failed to invalidate multi portfolio cache")


def _normalize_exchange_or_400(value: str | None) -> str:
    exchange = (value or DEFAULT_EXCHANGE).strip().lower()
    if exchange not in SUPPORTED_EXCHANGES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported exchange {exchange!r}; "
                f"expected one of {list(SUPPORTED_EXCHANGES)}"
            ),
        )
    return exchange


def _binance_base_url(testnet: bool) -> str:
    return BINANCE_TESTNET if testnet else BINANCE_MAINNET


def _summary(record, exchange: str) -> dict[str, Any]:
    if record is None or not record.is_configured:
        return {
            "exchange": exchange,
            "configured": False,
            "api_key_masked": "",
            "testnet": False,
            "updated_at": None,
        }
    return {
        "exchange": exchange,
        "configured": True,
        "api_key_masked": mask_secret(record.api_key),
        "testnet": bool(record.testnet),
        "updated_at": record.updated_at,
    }


@router.get("/settings/exchange")
def get_exchange_settings(
    exchange: str = Query(default=DEFAULT_EXCHANGE),
) -> dict[str, Any]:
    """Return the current credential summary (masked) for the given exchange."""

    exchange = _normalize_exchange_or_400(exchange)
    try:
        record = load_exchange_credentials(exchange=exchange)
    except Exception as exc:  # decryption or storage failure
        logger.exception("Failed to load %s credentials from store", exchange)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _summary(record, exchange)


@router.get("/settings/exchange/list")
def list_exchange_settings() -> dict[str, Any]:
    """Return credential summaries for every supported exchange."""

    out: dict[str, Any] = {"exchanges": []}
    for name in SUPPORTED_EXCHANGES:
        try:
            record = load_exchange_credentials(exchange=name)
        except Exception:
            logger.exception("Failed to load %s credentials from store", name)
            record = None
        out["exchanges"].append(_summary(record, name))
    return out


def _portfolio_summary() -> dict[str, Any]:
    preferences = load_portfolio_preferences()
    return {
        "view_mode": preferences.view_mode,
        "multi_exchange_enabled": preferences.multi_exchange_enabled,
        "active_execution_exchange": preferences.active_execution_exchange,
        "execution_scope": "single_exchange",
        "read_only_aggregation": True,
    }


@router.get("/settings/portfolio")
def get_portfolio_settings() -> dict[str, Any]:
    """Return multi-exchange view and single-exchange execution preferences."""

    try:
        return _portfolio_summary()
    except Exception as exc:
        logger.exception("Failed to load portfolio preferences")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.put("/settings/portfolio")
def update_portfolio_settings(payload: dict[str, Any]) -> dict[str, Any]:
    """Save portfolio view preferences without enabling order execution."""

    try:
        current = load_portfolio_preferences()
        save_portfolio_preferences(
            active_execution_exchange=str(
                payload.get(
                    "active_execution_exchange",
                    current.active_execution_exchange,
                )
            ),
            view_mode=str(payload.get("view_mode", current.view_mode)),
        )
        _invalidate_multi_portfolio_cache()
        return _portfolio_summary()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to save portfolio preferences")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _execution_summary() -> dict[str, Any]:
    execution = load_execution_preferences()
    portfolio = load_portfolio_preferences()
    credentials = load_exchange_credentials(exchange=portfolio.active_execution_exchange)
    configured = bool(credentials and credentials.is_configured)
    return {
        "mode": execution.mode,
        "live_confirmed": execution.live_confirmed,
        "network_enabled": execution.network_enabled and configured,
        "primary_exchange": portfolio.active_execution_exchange,
        "credentials_configured": configured,
        "live_confirmation_phrase": LIVE_CONFIRMATION,
    }


@router.get("/settings/llm")
def get_llm_settings() -> dict[str, Any]:
    return load_llm_preferences().to_dict()


@router.put("/settings/llm/provider")
def update_llm_provider(payload: dict[str, Any]) -> dict[str, Any]:
    base_url = str(payload.get("base_url", "")).strip()
    api_key_value = payload.get("api_key")
    api_key = None if api_key_value is None else str(api_key_value).strip()
    timeout = payload.get("timeout_seconds")
    try:
        timeout_seconds = int(timeout) if timeout is not None else None
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="invalid timeout_seconds") from exc
    if api_key is not None and bool(api_key) is False:
        api_key = ""
    return save_llm_provider(
        base_url=base_url,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
    ).to_dict()


@router.put("/settings/llm/agents")
def update_llm_agent_models(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("agent_models", payload)
    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="agent_models must be an object")
    filtered = {agent: raw.get(agent) for agent in LLM_AGENTS}
    return save_agent_models(filtered).to_dict()


@router.post("/settings/llm/models")
def fetch_llm_models() -> dict[str, Any]:
    prefs = load_llm_preferences()
    api_key = load_llm_api_key()
    if not prefs.base_url or not api_key:
        raise HTTPException(status_code=400, detail="llm_provider_not_configured")
    try:
        client = OpenAICompatibleClient(LLMClientConfig(
            base_url=prefs.base_url,
            api_key=api_key,
            model="__models__",
            timeout_seconds=prefs.timeout_seconds,
        ))
        models = client.list_models()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"model_fetch_failed: {exc}") from exc
    updated = save_llm_models(models)
    return {**updated.to_dict(), "ok": True, "models_found": len(models)}


@router.post("/settings/llm/test")
def test_llm_settings(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    prefs = load_llm_preferences()
    base_url = str(payload.get("base_url") or prefs.base_url).strip()
    api_key = str(payload.get("api_key") or load_llm_api_key() or "").strip()
    model = str(payload.get("model") or next(iter(prefs.models), "")).strip()
    if not base_url or not api_key:
        raise HTTPException(status_code=400, detail="base_url_and_api_key_required")
    try:
        client = OpenAICompatibleClient(LLMClientConfig(
            base_url=base_url,
            api_key=api_key,
            model=model or "__test__",
            timeout_seconds=prefs.timeout_seconds,
        ))
        models = client.list_models()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "base_url": base_url}
    return {"ok": True, "base_url": base_url, "models_found": len(models), "models": models[:50]}


@router.delete("/settings/llm")
def delete_llm_settings() -> dict[str, Any]:
    return clear_llm_provider().to_dict()


@router.get("/settings/execution")
def get_execution_settings() -> dict[str, Any]:
    return _execution_summary()


@router.put("/settings/execution")
def update_execution_settings(payload: dict[str, Any]) -> dict[str, Any]:
    mode = str(payload.get("mode", "paper")).strip().lower()
    confirmation = str(payload.get("confirmation", ""))
    portfolio = load_portfolio_preferences()
    credentials = load_exchange_credentials(exchange=portfolio.active_execution_exchange)
    if mode == "live" and (credentials is None or not credentials.is_configured):
        raise HTTPException(
            status_code=400,
            detail=f"{portfolio.active_execution_exchange}_credentials_missing",
        )
    if mode == "live" and portfolio.active_execution_exchange != "bitunix":
        raise HTTPException(
            status_code=400,
            detail="live_execution_not_wired_for_selected_exchange",
        )
    if mode == "live" and credentials is not None:
        preflight = _perform_bitunix_test(
            credentials.api_key,
            credentials.api_secret,
            testnet=False,
        )
        if not preflight.get("ok"):
            raise HTTPException(
                status_code=400,
                detail=f"bitunix_preflight_failed: {preflight.get('error', 'unknown')}",
            )
    try:
        save_execution_preferences(mode=mode, confirmation=confirmation)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _invalidate_multi_portfolio_cache()
    return _execution_summary()


@router.post("/settings/execution/kill")
def trigger_execution_kill_switch() -> dict[str, Any]:
    kill_switch()
    _invalidate_multi_portfolio_cache()
    return _execution_summary()


def _optional_number(payload: dict[str, Any], key: str) -> float | None:
    value = payload.get(key)
    if value is None or value == "":
        return None
    return float(value)


def _trading_summary(exchange: str) -> dict[str, Any]:
    preferences = load_trading_preferences(exchange=exchange)
    options = leverage_options(exchange)
    return {
        "exchange": exchange,
        "take_profit_percent": preferences.take_profit_percent,
        "stop_loss_percent": preferences.stop_loss_percent,
        "trailing_stop_percent": preferences.trailing_stop_percent,
        "leverage": preferences.leverage,
        "leverage_min": options[0],
        "leverage_max": options[-1],
        "leverage_options": options,
        "updated_at": preferences.updated_at,
    }


@router.get("/settings/trading")
def get_trading_settings(
    exchange: str = Query(default=DEFAULT_EXCHANGE),
) -> dict[str, Any]:
    exchange = _normalize_exchange_or_400(exchange)
    try:
        return _trading_summary(exchange)
    except Exception as exc:
        logger.exception("Failed to load %s trading preferences", exchange)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.put("/settings/trading")
def update_trading_settings(payload: dict[str, Any]) -> dict[str, Any]:
    exchange = _normalize_exchange_or_400(payload.get("exchange"))
    try:
        leverage_raw = payload.get("leverage")
        leverage = (
            None
            if leverage_raw is None or leverage_raw == ""
            else int(leverage_raw)
        )
        save_trading_preferences(
            exchange=exchange,
            take_profit_percent=_optional_number(payload, "take_profit_percent"),
            stop_loss_percent=_optional_number(payload, "stop_loss_percent"),
            trailing_stop_percent=_optional_number(payload, "trailing_stop_percent"),
            leverage=leverage,
        )
        return _trading_summary(exchange)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to save %s trading preferences", exchange)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.put("/settings/exchange")
def update_exchange_settings(payload: dict[str, Any]) -> dict[str, Any]:
    """Store new credentials for the given exchange.

    Body: ``{"exchange": "binance|bitunix", "api_key": "...", "api_secret": "...", "testnet": false}``.
    """

    exchange = _normalize_exchange_or_400(payload.get("exchange"))
    api_key = str(payload.get("api_key", "")).strip()
    api_secret = str(payload.get("api_secret", "")).strip()
    # Bitunix has no public testnet. Never persist a stale Binance checkbox
    # value under the Bitunix credential namespace.
    testnet = bool(payload.get("testnet", False)) if exchange == "binance" else False

    if not api_key or not api_secret:
        raise HTTPException(
            status_code=400,
            detail="api_key and api_secret are required",
        )

    try:
        record = save_exchange_credentials(
            api_key, api_secret, testnet=testnet, exchange=exchange
        )
    except Exception as exc:
        logger.exception("Failed to persist %s credentials", exchange)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    _invalidate_multi_portfolio_cache()
    return _summary(record, exchange)


@router.delete("/settings/exchange")
def delete_exchange_settings(
    exchange: str = Query(default=DEFAULT_EXCHANGE),
) -> dict[str, Any]:
    exchange = _normalize_exchange_or_400(exchange)
    try:
        clear_exchange_credentials(exchange=exchange)
    except Exception as exc:
        logger.exception("Failed to clear %s credentials", exchange)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    _invalidate_multi_portfolio_cache()
    return _summary(None, exchange)


@router.post("/settings/exchange/test")
def test_exchange_settings(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Test connectivity to the exchange using stored (or supplied) credentials."""

    payload = payload or {}
    exchange = _normalize_exchange_or_400(payload.get("exchange"))
    api_key = str(payload.get("api_key", "")).strip()
    api_secret = str(payload.get("api_secret", "")).strip()
    testnet_override = payload.get("testnet")

    if bool(api_key) != bool(api_secret):
        raise HTTPException(
            status_code=400,
            detail="api_key and api_secret must be provided together",
        )

    if not (api_key and api_secret):
        record = load_exchange_credentials(exchange=exchange)
        if record is None or not record.is_configured:
            raise HTTPException(
                status_code=400,
                detail="No credentials stored; provide api_key and api_secret in body",
            )
        api_key = record.api_key
        api_secret = record.api_secret
        testnet = (
            record.testnet if testnet_override is None else bool(testnet_override)
        )
    else:
        testnet = bool(testnet_override) if testnet_override is not None else False

    if exchange == "binance":
        return _perform_binance_test(api_key, api_secret, testnet=testnet)
    if exchange == "bitunix":
        return _perform_bitunix_test(api_key, api_secret, testnet=False)

    # Should be unreachable because _normalize_exchange_or_400 gates the input.
    raise HTTPException(status_code=400, detail=f"unsupported exchange {exchange!r}")


def _perform_binance_test(
    api_key: str, api_secret: str, *, testnet: bool
) -> dict[str, Any]:
    query = urllib.parse.urlencode(
        {"timestamp": int(time.time() * 1000), "recvWindow": 5000}
    )
    signature = hmac.new(
        api_secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    url = f"{_binance_base_url(testnet)}/api/v3/account?{query}&signature={signature}"
    request = urllib.request.Request(
        url, headers={"X-MBX-APIKEY": api_key}, method="GET"
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            body = response.read().decode("utf-8")
            data = json.loads(body)
    except urllib.error.HTTPError as exc:
        detail_text = (
            exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        )
        try:
            detail = json.loads(detail_text) if detail_text else {}
        except json.JSONDecodeError:
            detail = {"raw": detail_text}
        return {
            "ok": False,
            "exchange": "binance",
            "status_code": exc.code,
            "error": detail.get("msg", detail.get("raw", "http_error")),
            "code": detail.get("code"),
            "testnet": testnet,
        }
    except urllib.error.URLError as exc:
        return {
            "ok": False,
            "exchange": "binance",
            "status_code": None,
            "error": f"network_error: {exc.reason}",
            "testnet": testnet,
        }
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Unexpected error while calling Binance /api/v3/account")
        return {
            "ok": False,
            "exchange": "binance",
            "status_code": None,
            "error": f"unexpected_error: {exc}",
            "testnet": testnet,
        }

    balances = [
        b
        for b in data.get("balances", [])
        if float(b.get("free", 0)) > 0 or float(b.get("locked", 0)) > 0
    ]
    return {
        "ok": True,
        "exchange": "binance",
        "status_code": 200,
        "account_type": data.get("accountType"),
        "can_trade": data.get("canTrade"),
        "can_withdraw": data.get("canWithdraw"),
        "permissions": data.get("permissions", []),
        "non_zero_balances": len(balances),
        "balances": balances,
        "testnet": testnet,
    }


def _bitunix_sign(
    *,
    api_key: str,
    api_secret: str,
    nonce: str,
    timestamp: str,
    query_params: str,
    body: str,
) -> str:
    """Two-pass SHA256 signature per Bitunix Futures spec.

    digest = sha256_hex(nonce + timestamp + api_key + query_params + body)
    sign   = sha256_hex(digest + api_secret)
    """

    digest_input = f"{nonce}{timestamp}{api_key}{query_params}{body}"
    digest = hashlib.sha256(digest_input.encode("utf-8")).hexdigest()
    return hashlib.sha256(f"{digest}{api_secret}".encode("utf-8")).hexdigest()


def _perform_bitunix_test(
    api_key: str, api_secret: str, *, testnet: bool
) -> dict[str, Any]:
    # Bitunix does not offer a public testnet; the flag is stored for future
    # use but the request always hits the production futures endpoint.
    params = {"marginCoin": "USDT"}
    # Signature expects query params concatenated in ascending ASCII order by
    # key with no separators, values as-is (per official spec/demo).
    query_params_for_sign = "".join(
        f"{k}{params[k]}" for k in sorted(params)
    )
    nonce = secrets.token_hex(16)
    timestamp = str(int(time.time() * 1000))
    sign = _bitunix_sign(
        api_key=api_key,
        api_secret=api_secret,
        nonce=nonce,
        timestamp=timestamp,
        query_params=query_params_for_sign,
        body="",
    )
    query_string = urllib.parse.urlencode(params)
    url = f"{BITUNIX_FUTURES_BASE}/api/v1/futures/account?{query_string}"
    request = urllib.request.Request(
        url,
        headers={
            "api-key": api_key,
            "sign": sign,
            "nonce": nonce,
            "timestamp": timestamp,
            "language": "en-US",
            "Content-Type": "application/json",
            # Bitunix' edge sits behind Cloudflare, which rejects the default
            # ``Python-urllib/X.Y`` UA with HTTP 403 + body ``error code: 1010``
            # ("banned browser signature") before the request ever reaches the
            # API. Sending a normal UA is enough to pass the integrity check.
            "User-Agent": BITUNIX_USER_AGENT,
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            body = response.read().decode("utf-8")
            data = json.loads(body)
    except urllib.error.HTTPError as exc:
        detail_text = (
            exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        )
        try:
            detail = json.loads(detail_text) if detail_text else {}
        except json.JSONDecodeError:
            detail = {"raw": detail_text}
        return {
            "ok": False,
            "exchange": "bitunix",
            "status_code": exc.code,
            "error": detail.get("msg", detail.get("raw", "http_error")),
            "code": detail.get("code"),
            "testnet": testnet,
        }
    except urllib.error.URLError as exc:
        return {
            "ok": False,
            "exchange": "bitunix",
            "status_code": None,
            "error": f"network_error: {exc.reason}",
            "testnet": testnet,
        }
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Unexpected error while calling Bitunix /futures/account")
        return {
            "ok": False,
            "exchange": "bitunix",
            "status_code": None,
            "error": f"unexpected_error: {exc}",
            "testnet": testnet,
        }

    # Bitunix returns {"code":0,"data":[{...}],"msg":"Success"} on success and
    # a non-zero code with an error message otherwise.
    code = data.get("code")
    if code != 0:
        return {
            "ok": False,
            "exchange": "bitunix",
            "status_code": 200,
            "error": data.get("msg") or "unknown error",
            "code": code,
            "testnet": testnet,
        }
    entries = data.get("data") or []
    if isinstance(entries, list):
        entry = entries[0] if entries and isinstance(entries[0], dict) else {}
    elif isinstance(entries, dict):
        entry = entries
    else:
        entry = {}
    return {
        "ok": True,
        "exchange": "bitunix",
        "status_code": 200,
        "margin_coin": entry.get("marginCoin"),
        "available": entry.get("available"),
        "position_mode": entry.get("positionMode"),
        "cross_unrealized_pnl": entry.get("crossUnrealizedPNL"),
        "isolation_unrealized_pnl": entry.get("isolationUnrealizedPNL"),
        "testnet": testnet,
    }


# ---------------------------------------------------------------------------
# Bot service restart — used by Settings > Restart Bot button.
# Runs ``systemctl restart`` via subprocess so operator tidak perlu SSH.
# A file lock (atomic create) mencegah double-klik trigger restart ganda.
# ---------------------------------------------------------------------------
import os
import tempfile

_RESTART_LOCK = os.path.join(tempfile.gettempdir(), "crypto-quant-bot-restart.lock")


@router.post("/settings/restart")
def restart_bot_services() -> dict[str, Any]:
    """Restart both systemd services (realtime + api) without spawning doubles.

    Mengandalkan ``systemctl restart`` yang idempotent: jika service sedang
    berjalan, ia direstart; jika berhenti, ia di-start. Tidak ada duplikat
    proses karena systemd menjamin satu instance per unit.
    """
    import subprocess

    # Lock: cegah double-klik. Auto-expire 60s kalau process crash & lock nyangkut.
    import time
    try:
        if os.path.exists(_RESTART_LOCK):
            age = time.time() - os.path.getmtime(_RESTART_LOCK)
            if age > 60:
                os.unlink(_RESTART_LOCK)
        fd = os.open(_RESTART_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except FileExistsError:
        return {
            "ok": False,
            "error": "restart_already_in_progress",
            "hint": "Tunggu restart sebelumnya selesai (~5-10 detik).",
        }

    # ponytail: API process akan terbunuh saat crypto-quant-bot-api restart.
    # Jadi restart crypto-quant-bot dulu, LALU api terakhir (request ini).
    results: dict[str, str] = {}
    try:
        for service in ("crypto-quant-bot.service",):
            try:
                proc = subprocess.run(
                    ["systemctl", "restart", service],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                results[service] = "ok" if proc.returncode == 0 else (
                    f"error: {proc.stderr.strip() or proc.stdout.strip() or 'unknown'}"
                )
            except FileNotFoundError:
                results[service] = "error: systemctl not found"
            except subprocess.TimeoutExpired:
                results[service] = "error: timeout"

        # Restart api service terpisah (process ini akan terbunuh).
        try:
            subprocess.Popen(
                ["systemctl", "restart", "crypto-quant-bot-api.service"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            results["crypto-quant-bot-api.service"] = "ok"
        except Exception as exc:  # noqa: BLE001
            results["crypto-quant-bot-api.service"] = f"error: {exc}"

        ok = all(v == "ok" for v in results.values())
        return {"ok": ok, "services": results}
    finally:
        try:
            os.unlink(_RESTART_LOCK)
        except OSError:
            pass

