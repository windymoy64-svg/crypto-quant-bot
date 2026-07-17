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


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["settings"])

BINANCE_MAINNET = "https://api.binance.com"
BINANCE_TESTNET = "https://testnet.binance.vision"
BITUNIX_FUTURES_BASE = "https://fapi.bitunix.com"
# Bitunix' edge is fronted by Cloudflare, which returns HTTP 403 with
# ``error code: 1010`` (banned browser signature) for the default
# ``Python-urllib/X.Y`` User-Agent. Any plausible UA passes the check.
BITUNIX_USER_AGENT = "crypto-quant-bot/1.0 (+dashboard)"


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


@router.put("/settings/exchange")
def update_exchange_settings(payload: dict[str, Any]) -> dict[str, Any]:
    """Store new credentials for the given exchange.

    Body: ``{"exchange": "binance|bitunix", "api_key": "...", "api_secret": "...", "testnet": false}``.
    """

    exchange = _normalize_exchange_or_400(payload.get("exchange"))
    api_key = str(payload.get("api_key", "")).strip()
    api_secret = str(payload.get("api_secret", "")).strip()
    testnet = bool(payload.get("testnet", False))

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
    return _summary(None, exchange)


@router.post("/settings/exchange/test")
def test_exchange_settings(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Test connectivity to the exchange using stored (or supplied) credentials."""

    payload = payload or {}
    exchange = _normalize_exchange_or_400(payload.get("exchange"))
    api_key = str(payload.get("api_key", "")).strip()
    api_secret = str(payload.get("api_secret", "")).strip()
    testnet_override = payload.get("testnet")

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
        return _perform_bitunix_test(api_key, api_secret, testnet=testnet)

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
    entry = entries[0] if entries else {}
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

