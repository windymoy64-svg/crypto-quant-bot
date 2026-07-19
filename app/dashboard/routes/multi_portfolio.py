"""Read-only multi-exchange portfolio endpoints.

The endpoint never creates, changes, or cancels exchange orders.  It is an
observability layer over the credentials stored for each supported exchange.
"""

from __future__ import annotations

import logging
import json
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from fastapi import APIRouter

from app.dashboard.routes.settings import (
    BITUNIX_FUTURES_BASE,
    BITUNIX_USER_AGENT,
    _bitunix_sign,
    _perform_binance_test,
    _perform_bitunix_test,
)
from app.config.production import runtime_mode
from app.exchange.binance_futures.account import FuturesAccountReader
from app.exchange.binance_futures.client import (
    FuturesEndpoint,
    FuturesHttpClient,
    FuturesHttpError,
)
from app.settings.exchange_credentials import SUPPORTED_EXCHANGES, load_exchange_credentials
from app.settings.portfolio_preferences import load_portfolio_preferences


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["portfolio"])

# ---------------------------------------------------------------------------
# In-memory TTL cache untuk payload /api/portfolio/multi.
#
# Endpoint ini melakukan beberapa HTTP call sinkron ke exchange (account,
# pending positions, pending orders) per exchange yang dikonfigurasi. Tanpa
# cache, setiap pemanggil (refresh halaman + poller 5 detik di frontend)
# memukul exchange lagi, menambah ~300-400 ms latency per request. Cache
# singkat menjaga dashboard tetap "near realtime" tanpa membebani exchange.
# ---------------------------------------------------------------------------
_MULTI_CACHE_TTL_SECONDS = 5.0
_multi_cache_lock = threading.Lock()
_multi_cache_payload: dict[str, Any] | None = None
_multi_cache_expires_at: float = 0.0


def invalidate_multi_portfolio_cache() -> None:
    """Buang cache supaya request berikutnya membaca ulang dari exchange.

    Dipanggil setelah operator mengubah kredensial / preferensi portfolio /
    mode eksekusi agar perubahan langsung terlihat tanpa menunggu TTL.
    """

    global _multi_cache_payload, _multi_cache_expires_at
    with _multi_cache_lock:
        _multi_cache_payload = None
        _multi_cache_expires_at = 0.0


@router.get("/portfolio/multi")
def multi_portfolio() -> dict[str, Any]:
    """Return read-only account summaries for every configured exchange.

    Hasil di-cache singkat (TTL detik) karena builder-nya melakukan HTTP call
    sinkron ke exchange. Gunakan ``refresh=1`` untuk memaksa baca ulang.
    """

    now = time.monotonic()
    with _multi_cache_lock:
        if _multi_cache_payload is not None and now < _multi_cache_expires_at:
            return _multi_cache_payload

    payload = _build_multi_portfolio_payload()

    with _multi_cache_lock:
        globals()["_multi_cache_payload"] = payload
        globals()["_multi_cache_expires_at"] = now + _MULTI_CACHE_TTL_SECONDS
    return payload


def _build_multi_portfolio_payload() -> dict[str, Any]:
    """Susun payload multi-portfolio dengan membaca langsung dari exchange.

    Balances are deliberately kept per exchange/currency.  Summing arbitrary
    exchange balances as USD without a live conversion source would be false
    precision and unsafe for risk decisions.
    """

    preferences = load_portfolio_preferences()
    accounts = [_account_snapshot(exchange) for exchange in SUPPORTED_EXCHANGES]
    connected = [account for account in accounts if account["status"] == "connected"]
    visible = _visible_accounts(
        accounts,
        view_mode=preferences.view_mode,
        active_exchange=preferences.active_execution_exchange,
    )
    positions = [position for account in visible for position in account["positions"]]
    open_orders = [order for account in visible for order in account["open_orders"]]
    environments = {"testnet" if account.get("testnet") else "mainnet" for account in visible}
    aggregate_available = (
        sum(_as_float(account.get("available_balance_usdt")) for account in visible)
        if len(environments) <= 1
        else None
    )
    return {
        "view_mode": preferences.view_mode,
        "multi_exchange_enabled": preferences.multi_exchange_enabled,
        "active_execution_exchange": preferences.active_execution_exchange,
        "bot_mode": runtime_mode(),
        "accounts": accounts,
        "accounts_configured": sum(account["configured"] for account in accounts),
        "accounts_connected": len(connected),
        "displayed_exchanges": [account["exchange"] for account in visible],
        "account_environment": (
            next(iter(environments), "paper") if len(environments) == 1 else "mixed"
        ),
        "available_balance_usdt": aggregate_available,
        "open_positions_count": len(positions),
        "open_orders_count": len(open_orders),
        "positions": positions,
        "open_orders": open_orders,
        "read_only": True,
        "aggregation_note": (
            "Balances are reported per exchange and currency; no cross-asset "
            "total is calculated without an explicit valuation feed. Testnet "
            "and mainnet balances are never combined."
        ),
    }


def _account_snapshot(exchange: str) -> dict[str, Any]:
    try:
        credentials = load_exchange_credentials(exchange=exchange)
    except Exception as exc:  # pragma: no cover - defensive storage handling
        logger.exception("Could not load %s credentials", exchange)
        return _error_account(exchange, "credentials_error", str(exc))

    if credentials is None or not credentials.is_configured:
        return {
            "exchange": exchange,
            "configured": False,
            "status": "not_configured",
            "testnet": False,
            "balances": [],
            "positions": [],
            "open_orders": [],
            "warnings": [],
            "available_balance_usdt": 0.0,
            "read_only": True,
        }

    try:
        if exchange == "binance":
            result = _perform_binance_test(
                credentials.api_key,
                credentials.api_secret,
                testnet=credentials.testnet,
            )
        else:
            result = _perform_bitunix_test(
                credentials.api_key,
                credentials.api_secret,
                testnet=False,
            )
    except Exception as exc:  # one account must never break the aggregate endpoint
        logger.warning("Could not connect to %s account", exchange, exc_info=True)
        return _error_account(
            exchange,
            "connection_error",
            str(exc),
            testnet=credentials.testnet if exchange == "binance" else False,
        )

    if not result.get("ok"):
        return _error_account(
            exchange,
            "connection_error",
            str(result.get("error") or "exchange connection failed"),
            testnet=bool(result.get("testnet")),
        )

    try:
        details = (
            _load_binance_details(
                credentials.api_key, credentials.api_secret, credentials.testnet
            )
            if exchange == "binance"
            else _load_bitunix_details(credentials.api_key, credentials.api_secret)
        )
    except Exception as exc:  # pragma: no cover - last-resort partial-success guard
        logger.warning("Could not load optional %s account details", exchange, exc_info=True)
        details = {
            "balances": [],
            "positions": [],
            "open_orders": [],
            "warnings": [f"account_details: {exc}"],
        }
    balances = _balances(exchange, result)
    detail_balances = details.get("balances")
    if isinstance(detail_balances, list):
        balances.extend(item for item in detail_balances if isinstance(item, dict))
    return {
        "exchange": exchange,
        "configured": True,
        "status": "connected",
        "testnet": bool(result.get("testnet")),
        "balances": balances,
        "positions": details.get("positions", []),
        "open_orders": details.get("open_orders", []),
        "warnings": details.get("warnings", []),
        "available_balance_usdt": _available_usdt(exchange, result, details),
        "read_only": True,
    }


def _visible_accounts(
    accounts: list[dict[str, Any]], *, view_mode: str, active_exchange: str
) -> list[dict[str, Any]]:
    connected = [account for account in accounts if account.get("status") == "connected"]
    if view_mode == "multi":
        return connected
    active = [
        account for account in connected if account.get("exchange") == active_exchange
    ]
    if active:
        return active
    # If only one credential is configured, switch the read-only Overview to
    # that real account automatically while execution preference remains intact.
    return connected[:1]


def _load_binance_details(
    api_key: str, api_secret: str, testnet: bool
) -> dict[str, Any]:
    endpoint = FuturesEndpoint.TESTNET if testnet else FuturesEndpoint.MAINNET
    client = FuturesHttpClient(api_key, api_secret, endpoint=endpoint)
    warnings: list[str] = []
    balances: list[dict[str, Any]] = []
    positions: list[dict[str, Any]] = []
    open_orders: list[dict[str, Any]] = []
    try:
        snapshot = FuturesAccountReader(client).snapshot()
        balances = [
            {
                "asset": item.asset,
                "wallet_balance": item.wallet_balance,
                "available_balance": item.available_balance,
                "unrealized_pnl": item.cross_unrealized_pnl,
                "wallet": "futures",
            }
            for item in snapshot.balances
            if item.wallet_balance or item.available_balance
        ]
        positions = [
            {
                "exchange": "binance",
                "symbol": item.symbol,
                "side": _binance_position_side(item.position_side, item.position_amount),
                "quantity": abs(item.position_amount),
                "entry_price": item.entry_price,
                "mark_price": item.mark_price,
                "unrealized_pnl": item.unrealized_profit,
                "leverage": item.leverage,
                "liquidation_price": item.liquidation_price,
                "margin_type": item.margin_type,
            }
            for item in snapshot.positions
            if item.position_amount
        ]
    except (FuturesHttpError, ValueError) as exc:
        warnings.append(f"futures_account: {exc}")

    try:
        response = client.get("/fapi/v1/openOrders")
        rows = response.body if isinstance(response.body, list) else []
        open_orders = [
            {
                "exchange": "binance",
                "order_id": row.get("orderId"),
                "symbol": row.get("symbol"),
                "side": row.get("side"),
                "type": row.get("type"),
                "status": row.get("status"),
                "price": row.get("price"),
                "quantity": row.get("origQty"),
                "executed_quantity": row.get("executedQty"),
                "reduce_only": row.get("reduceOnly"),
            }
            for row in rows
            if isinstance(row, dict)
        ]
    except (FuturesHttpError, ValueError) as exc:
        warnings.append(f"futures_open_orders: {exc}")

    return {
        "balances": balances,
        "positions": positions,
        "open_orders": open_orders,
        "warnings": warnings,
    }


def _load_bitunix_details(api_key: str, api_secret: str) -> dict[str, Any]:
    warnings: list[str] = []
    positions: list[dict[str, Any]] = []
    open_orders: list[dict[str, Any]] = []
    try:
        payload = _bitunix_private_get(
            api_key,
            api_secret,
            "/api/v1/futures/position/get_pending_positions",
        )
        positions = [_normalize_bitunix_position(row) for row in _extract_rows(
            payload, "positionList", "positions", "list"
        )]
    except RuntimeError as exc:
        warnings.append(f"pending_positions: {exc}")

    try:
        payload = _bitunix_private_get(
            api_key,
            api_secret,
            "/api/v1/futures/trade/get_pending_orders",
        )
        open_orders = [_normalize_bitunix_order(row) for row in _extract_rows(
            payload, "orderList", "orders", "list"
        )]
    except RuntimeError as exc:
        warnings.append(f"pending_orders: {exc}")

    return {
        "balances": [],
        "positions": positions,
        "open_orders": open_orders,
        "warnings": warnings,
    }


def _bitunix_private_get(
    api_key: str,
    api_secret: str,
    path: str,
    params: dict[str, Any] | None = None,
) -> Any:
    query = dict(params or {})
    canonical = "".join(f"{key}{query[key]}" for key in sorted(query))
    nonce = secrets.token_hex(16)
    timestamp = str(int(time.time() * 1000))
    signature = _bitunix_sign(
        api_key=api_key,
        api_secret=api_secret,
        nonce=nonce,
        timestamp=timestamp,
        query_params=canonical,
        body="",
    )
    query_string = urllib.parse.urlencode(query)
    url = f"{BITUNIX_FUTURES_BASE}{path}"
    if query_string:
        url = f"{url}?{query_string}"
    request = urllib.request.Request(
        url,
        headers={
            "api-key": api_key,
            "sign": signature,
            "nonce": nonce,
            "timestamp": timestamp,
            "language": "en-US",
            "Content-Type": "application/json",
            "User-Agent": BITUNIX_USER_AGENT,
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read().decode("utf-8")
            payload = json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        raise RuntimeError(raw or f"HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"network_error: {exc.reason}") from exc
    except (json.JSONDecodeError, OSError) as exc:
        raise RuntimeError(str(exc)) from exc
    if not isinstance(payload, dict) or payload.get("code") != 0:
        message = payload.get("msg") if isinstance(payload, dict) else "invalid response"
        raise RuntimeError(str(message or "Bitunix request failed"))
    return payload.get("data")


def _extract_rows(payload: Any, *keys: str) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    return []


def _normalize_bitunix_position(row: dict[str, Any]) -> dict[str, Any]:
    quantity = _as_float(row.get("qty", row.get("positionQty", row.get("amount"))))
    return {
        "exchange": "bitunix",
        "position_id": row.get("positionId"),
        "symbol": row.get("symbol"),
        "side": str(row.get("side") or row.get("positionSide") or "").upper(),
        "quantity": abs(quantity),
        "entry_price": row.get("avgOpenPrice", row.get("entryPrice")),
        "mark_price": row.get("markPrice"),
        "unrealized_pnl": row.get("unrealizedPNL", row.get("unrealizedPnl")),
        "leverage": row.get("leverage"),
        "liquidation_price": row.get("liqPrice", row.get("liquidationPrice")),
        "margin_type": row.get("marginMode", row.get("marginType")),
    }


def _normalize_bitunix_order(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "exchange": "bitunix",
        "order_id": row.get("orderId"),
        "client_order_id": row.get("clientId"),
        "symbol": row.get("symbol"),
        "side": row.get("side"),
        "type": row.get("orderType", row.get("type")),
        "status": row.get("status"),
        "price": row.get("price"),
        "quantity": row.get("qty", row.get("quantity")),
        "executed_quantity": row.get("dealVolume", row.get("filledQty")),
        "reduce_only": row.get("reduceOnly"),
    }


def _binance_position_side(position_side: str, quantity: float) -> str:
    normalized = str(position_side).upper()
    if normalized in {"LONG", "SHORT"}:
        return normalized
    return "SHORT" if quantity < 0 else "LONG"


def _available_usdt(
    exchange: str, result: dict[str, Any], details: dict[str, Any]
) -> float:
    if exchange == "bitunix":
        return _as_float(result.get("available"))
    spot = sum(
        _as_float(row.get("free"))
        for row in result.get("balances", [])
        if isinstance(row, dict) and str(row.get("asset", "")).upper() == "USDT"
    )
    futures = sum(
        _as_float(row.get("available_balance"))
        for row in details.get("balances", [])
        if isinstance(row, dict) and str(row.get("asset", "")).upper() == "USDT"
    )
    return spot + futures


def _balances(exchange: str, result: dict[str, Any]) -> list[dict[str, Any]]:
    if exchange == "bitunix":
        return [
            {
                "asset": str(result.get("margin_coin") or "USDT"),
                "available": result.get("available"),
                "unrealized_pnl": _sum_numbers(
                    result.get("cross_unrealized_pnl"),
                    result.get("isolation_unrealized_pnl"),
                ),
            }
        ]

    rows = result.get("balances")
    if not isinstance(rows, list):
        return []
    return [
        {
            "asset": str(row.get("asset") or ""),
            "free": row.get("free"),
            "locked": row.get("locked"),
        }
        for row in rows
        if isinstance(row, dict)
        and (str(row.get("free", "0")) != "0" or str(row.get("locked", "0")) != "0")
    ]


def _sum_numbers(*values: object) -> float:
    total = 0.0
    for value in values:
        try:
            total += float(value or 0)
        except (TypeError, ValueError):
            continue
    return total


def _as_float(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _error_account(
    exchange: str,
    status: str,
    error: str,
    *,
    testnet: bool = False,
) -> dict[str, Any]:
    return {
        "exchange": exchange,
        "configured": status != "credentials_error",
        "status": status,
        "testnet": testnet,
        "balances": [],
        "positions": [],
        "open_orders": [],
        "warnings": [],
        "available_balance_usdt": 0.0,
        "error": error,
        "read_only": True,
    }