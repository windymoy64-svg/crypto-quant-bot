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
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
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
BITUNIX_ORDER_METADATA_PATH = "logs/bitunix_order_metadata.json"

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
_BITUNIX_DETAIL_TIMEOUT_SECONDS = 5.0
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


def cached_multi_portfolio() -> dict[str, Any] | None:
    """Return the last snapshot without refreshing private exchange APIs."""
    with _multi_cache_lock:
        return _multi_cache_payload


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
    order_history = [order for account in visible for order in account.get("order_history", [])]
    closed_positions = [position for account in visible for position in account.get("closed_positions", [])]
    environments = {"testnet" if account.get("testnet") else "mainnet" for account in visible}
    aggregate_available = (
        sum(_as_float(account.get("available_balance_usdt")) for account in visible)
        if len(environments) <= 1
        else None
    )
    aggregate_balance = (
        sum(_as_float(account.get("account_balance_usdt")) for account in visible)
        if len(environments) <= 1
        else None
    )
    aggregate_equity = (
        sum(_as_float(account.get("equity_usdt")) for account in visible)
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
        "exchange_data_available": bool(connected),
        "exchange_data_status": (
            "connected" if connected else
            "unavailable" if any(account.get("status") == "connection_error" for account in accounts)
            else "not_configured"
        ),
        "displayed_exchanges": [account["exchange"] for account in visible],
        "account_environment": (
            next(iter(environments), "paper") if len(environments) == 1 else "mixed"
        ),
        "available_balance_usdt": aggregate_available,
        "account_balance_usdt": aggregate_balance,
        "equity_usdt": aggregate_equity,
        "open_positions_count": len(positions),
        "open_orders_count": len(open_orders),
        "positions": positions,
        "open_orders": open_orders,
        "order_history": order_history,
        "closed_positions": closed_positions,
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
            "order_history": [],
            "closed_positions": [],
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
        "order_history": details.get("order_history", []),
        "closed_positions": details.get("closed_positions", []),
        "warnings": details.get("warnings", []),
        "available_balance_usdt": _available_usdt(exchange, result, details),
        "account_balance_usdt": _account_balance_usdt(exchange, result, details),
        "equity_usdt": _equity_usdt(exchange, result, details),
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
    requests = {
        "pending_positions": ("/api/v1/futures/position/get_pending_positions", None),
        "pending_tpsl": ("/api/v1/futures/tpsl/get_pending_orders", {"limit": 100}),
        "pending_orders": ("/api/v1/futures/trade/get_pending_orders", None),
        "closed_positions": ("/api/v1/futures/position/get_history_positions", {"limit": 100}),
    }

    def fetch(item: tuple[str, tuple[str, dict[str, Any] | None]]) -> tuple[str, Any, str | None]:
        name, (path, params) = item
        try:
            return name, _bitunix_private_get(api_key, api_secret, path, params), None
        except RuntimeError as exc:
            return name, None, str(exc)

    # Kelima endpoint bersifat GET/read-only dan independen. Menjalankannya
    # paralel mencegah latency dashboard menjadi jumlah seluruh timeout.
    with ThreadPoolExecutor(max_workers=len(requests), thread_name_prefix="bitunix-read") as pool:
        results = {name: (payload, error) for name, payload, error in pool.map(fetch, requests.items())}

    warnings = [f"{name}: {error}" for name, (_, error) in results.items() if error]
    positions = [_normalize_bitunix_position(row) for row in _extract_rows(
        results["pending_positions"][0], "positionList", "positions", "list"
    )]
    _attach_bitunix_position_tpsl(
        positions,
        _extract_rows(results["pending_tpsl"][0], "orderList", "orders", "list"),
    )
    open_orders = [_normalize_bitunix_order(row) for row in _extract_rows(
        results["pending_orders"][0], "orderList", "orders", "list"
    )]
    order_metadata = _load_bitunix_order_metadata()
    closed_positions = [_normalize_bitunix_closed_position(row) for row in _extract_rows(
        results["closed_positions"][0], "positionList", "positions", "list"
    )]
    closed_positions = _build_closed_position_history(closed_positions, order_metadata)

    return {
        "balances": [],
        "positions": positions,
        "open_orders": open_orders,
        # Completed-trade history comes from closed_positions. Do not fetch or
        # expose raw entry/TP/SL order history in the periodic dashboard poll.
        "order_history": [],
        "closed_positions": closed_positions,
        "warnings": warnings,
    }


def _attach_bitunix_position_tpsl(
    positions: list[dict[str, Any]], orders: list[dict[str, Any]]
) -> None:
    """Attach pending Bitunix TP/SL orders to their live positions."""
    for position in positions:
        position_id = str(position.get("position_id") or "")
        symbol = _compact_symbol(position.get("symbol"))
        matches = [order for order in orders if (
            (position_id and str(order.get("positionId") or "") == position_id)
            # Some Bitunix TPSL responses omit positionId even though the
            # position endpoint supplies it. In that case symbol is the only
            # stable read-only join key available.
            or (
                symbol
                and not order.get("positionId")
                and _compact_symbol(order.get("symbol")) == symbol
            )
        )]
        tp = next((_bitunix_protection_price(row, "tp") for row in matches
                   if _bitunix_protection_price(row, "tp") is not None), None)
        sl = next((_bitunix_protection_price(row, "sl") for row in matches
                   if _bitunix_protection_price(row, "sl") is not None), None)
        if tp is not None:
            position["take_profit"] = tp
        if sl is not None:
            position["stop_loss"] = sl
        tp_orders = [row for row in matches if _bitunix_protection_price(row, "tp") is not None]
        sl_orders = [row for row in matches if _bitunix_protection_price(row, "sl") is not None]
        position["take_profit_order_count"] = len(tp_orders)
        position["stop_loss_order_count"] = len(sl_orders)
        position["take_profit_total_quantity"] = sum(
            _as_float(row.get("tpQty", row.get("qty"))) for row in tp_orders
        )
        position["stop_loss_total_quantity"] = sum(
            _as_float(row.get("slQty", row.get("qty"))) for row in sl_orders
        )
        entry = _as_float(position.get("entry_price"))
        risk_distance = abs(entry - _as_float(position.get("stop_loss")))
        position["actual_risk_reward"] = (
            abs(entry - _as_float(position.get("take_profit"))) / risk_distance
            if entry > 0 and risk_distance > 0 and _as_float(position.get("take_profit")) > 0
            else None
        )


def _compact_symbol(value: Any) -> str:
    return "".join(char for char in str(value or "").upper() if char.isalnum())


def _bitunix_protection_price(row: dict[str, Any], kind: str) -> Any | None:
    """Read TP/SL trigger price across Bitunix response variants."""
    keys = (
        ("tpPrice", "takeProfitPrice", "tpTriggerPrice")
        if kind == "tp"
        else ("slPrice", "stopLossPrice", "slTriggerPrice")
    )
    candidates = [row]
    nested_keys = (
        ("tpOrder", "takeProfit")
        if kind == "tp"
        else ("slOrder", "stopLoss")
    )
    for nested_key in nested_keys:
        nested = row.get(nested_key)
        if isinstance(nested, dict):
            candidates.append(nested)
    for candidate in candidates:
        for key in keys:
            value = candidate.get(key)
            if _as_float(value) > 0:
                return value
        # A nested protection object may expose its trigger simply as price.
        if candidate is not row and _as_float(candidate.get("price")) > 0:
            return candidate.get("price")
    return None


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
        with urllib.request.urlopen(request, timeout=_BITUNIX_DETAIL_TIMEOUT_SECONDS) as response:
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
    entry_price = _as_float(row.get("avgOpenPrice", row.get("entryPrice")))
    unrealized_pnl = _as_float(row.get("unrealizedPNL", row.get("unrealizedPnl")))
    side = str(row.get("side") or row.get("positionSide") or "").upper()
    mark_price = row.get("markPrice")
    # Bitunix currently returns markPrice=null for some live positions while
    # unrealizedPNL remains fresh. Linear futures identity gives an exact
    # fallback: PnL = (mark-entry) * qty * direction.
    if _as_float(mark_price) <= 0 and entry_price > 0 and abs(quantity) > 0:
        direction = -1 if side in {"SHORT", "SELL"} else 1
        mark_price = entry_price + (unrealized_pnl / (abs(quantity) * direction))
    take_profit = row.get("tpPrice", row.get("takeProfitPrice"))
    stop_loss = row.get("slPrice", row.get("stopLossPrice"))
    risk_distance = abs(entry_price - _as_float(stop_loss))
    actual_risk_reward = (
        abs(entry_price - _as_float(take_profit)) / risk_distance
        if risk_distance > 0 and _as_float(take_profit) > 0
        else None
    )
    return {
        "exchange": "bitunix",
        "position_id": row.get("positionId"),
        "symbol": row.get("symbol"),
        "side": side,
        # A live position is one executed trade.  Preserve its exchange open
        # time so dashboard KPIs never have to infer entries from order
        # history (which also contains closes, TP/SL and duplicate updates).
        "opened_at": _millis_to_iso(row.get("ctime", row.get("createdTime"))),
        "quantity": abs(quantity),
        "entry_price": row.get("avgOpenPrice", row.get("entryPrice")),
        "mark_price": mark_price,
        "unrealized_pnl": row.get("unrealizedPNL", row.get("unrealizedPnl")),
        "leverage": row.get("leverage"),
        "liquidation_price": row.get("liqPrice", row.get("liquidationPrice")),
        "margin_type": row.get("marginMode", row.get("marginType")),
        # Bitunix returns attached position protection on the position row.
        # Preserve it for Active Orders instead of relying on pending orders:
        # attached TP/SL are not necessarily exposed as standalone orders.
        "take_profit": take_profit,
        "stop_loss": stop_loss,
        "actual_risk_reward": actual_risk_reward,
    }


def _normalize_bitunix_order(
    row: dict[str, Any], order_metadata: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    status = str(row.get("status") or "").strip().rstrip("_").upper()
    requested_quantity = row.get("qty", row.get("quantity"))
    executed_quantity = row.get("tradeQty", row.get("dealVolume", row.get("filledQty")))
    fill_price = next((value for value in (
        row.get("dealAvgPrice"), row.get("avgPrice"), row.get("averagePrice"),
        row.get("tradePrice"), row.get("filledPrice"), row.get("fillPrice"),
        row.get("price"),
    ) if _as_float(value) > 0), None)
    quantity_for_value = _as_float(executed_quantity) or _as_float(requested_quantity)
    leverage = max(_as_float(row.get("leverage")), 1.0)
    notional = _as_float(fill_price) * quantity_for_value
    realized = _as_float(row.get("realizedPNL", row.get("realizedPnl")))
    fee = _as_float(row.get("fee"))
    reduce_only = bool(row.get("reduceOnly"))
    metadata = (order_metadata or {}).get(str(row.get("orderId") or ""), {})
    bot_role = str(metadata.get("role") or "")
    bot_reason = str(metadata.get("reason") or "")
    has_bot_close_reason = bool(
        reduce_only
        and bot_reason
        and (bot_role == "exit" or bot_role == "stop_loss" or bot_role.startswith("take_profit_"))
    )
    if has_bot_close_reason:
        reason = bot_reason
    elif status in {"FILLED", "PART_FILLED", "PARTIAL"}:
        reason = "position_reduced" if reduce_only else "entry_filled"
    elif "CANCEL" in status:
        reason = "order_cancelled"
    elif "REJECT" in status or "FAIL" in status:
        reason = "order_rejected"
    else:
        reason = "exchange_order"
    return {
        "exchange": "bitunix",
        "order_id": row.get("orderId"),
        "client_order_id": row.get("clientId"),
        "symbol": row.get("symbol"),
        "side": row.get("side"),
        "type": row.get("orderType", row.get("type")),
        "order_type": row.get("orderType", row.get("type")),
        "status": status,
        "price": fill_price,
        "average_price": fill_price,
        "quantity": executed_quantity or requested_quantity,
        "requested_quantity": requested_quantity,
        "executed_quantity": executed_quantity,
        "reduce_only": reduce_only,
        "leverage": row.get("leverage"),
        "margin_type": row.get("marginMode"),
        "position_mode": row.get("positionMode"),
        "take_profit": row.get("tpPrice"),
        "stop_loss": row.get("slPrice"),
        "fee": fee,
        "realized_pnl": realized,
        "net_pnl": realized - fee if reduce_only else -fee,
        "notional": notional if notional > 0 else None,
        "modal": (notional / leverage) if notional > 0 else None,
        "created_at": _millis_to_iso(row.get("ctime")),
        "updated_at": _millis_to_iso(row.get("mtime")),
        "reason": reason,
        "bot_role": bot_role or None,
        "reason_source": "bot_order_metadata" if has_bot_close_reason else "bitunix_order_lifecycle",
        "close_scope": "partial" if bot_role.startswith("take_profit_") else ("full" if bot_role == "exit" else None),
        "close_label": (
            f"Partial close — {bot_reason.replace('_', ' ')}"
            if has_bot_close_reason and bot_role.startswith("take_profit_")
            else f"Full close — {bot_reason.replace('_', ' ')}"
            if has_bot_close_reason and bot_role in {"exit", "stop_loss"}
            else None
        ),
    }


def _load_bitunix_order_metadata() -> dict[str, dict[str, Any]]:
    try:
        with open(BITUNIX_ORDER_METADATA_PATH, encoding="utf-8") as file:
            payload = json.load(file)
    except (OSError, json.JSONDecodeError):
        return {}
    rows = payload.get("orders") if isinstance(payload, dict) else None
    if not isinstance(rows, dict):
        return {}
    return {
        str(order_id): dict(metadata)
        for order_id, metadata in rows.items()
        if isinstance(metadata, dict)
    }


def _build_closed_position_history(
    positions: list[dict[str, Any]], order_metadata: dict[str, dict[str, Any]],
    *, now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Return one current-WIB-session row per fully closed exchange position.

    Exchange order history contains entry, TP, SL, partial and exit orders. The
    dashboard instead represents a completed trade, using entry economics from
    position history and the exact bot exit reason correlated by position ID.
    """
    current = (now or datetime.now(tz=UTC)).astimezone(UTC)
    session_start = current.replace(hour=0, minute=0, second=0, microsecond=0)
    reasons_by_position: dict[str, dict[str, Any]] = {}
    protection_by_position: dict[str, list[dict[str, Any]]] = {}
    for metadata in order_metadata.values():
        position_id = str(metadata.get("position_id") or "")
        role = str(metadata.get("role") or "")
        reason = metadata.get("reason")
        if position_id and metadata.get("metadata_kind") == "protection_intent":
            protection_by_position.setdefault(position_id, []).append(metadata)
            continue
        if (
            not position_id
            or not reason
            or (role not in {"exit", "stop_loss"} and not role.startswith("take_profit_"))
        ):
            continue
        previous = reasons_by_position.get(position_id)
        if previous is None or str(metadata.get("created_at") or "") >= str(previous.get("created_at") or ""):
            reasons_by_position[position_id] = metadata

    history: list[dict[str, Any]] = []
    seen: set[str] = set()
    for position in positions:
        position_id = str(position.get("position_id") or "")
        closed_at = _parse_iso_datetime(position.get("closed_at"))
        if closed_at is None or closed_at < session_start or closed_at > current:
            continue
        dedupe_key = position_id or f"{position.get('symbol')}:{position.get('closed_at')}"
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        entry_price = _as_float(position.get("entry_price"))
        quantity = abs(_as_float(position.get("quantity")))
        leverage = max(_as_float(position.get("leverage")), 1.0)
        metadata = reasons_by_position.get(position_id, {})
        reason = metadata.get("reason")
        reason_source = "bot_order_metadata" if reason else ""
        if not reason:
            reason, reason_source = _infer_closed_position_reason(
                position, protection_by_position.get(position_id, [])
            )
        history.append({
            **position,
            "status": "CLOSED",
            "price": entry_price or None,
            "entry": entry_price or None,
            "quantity": quantity,
            "modal": (entry_price * quantity / leverage) if entry_price and quantity else None,
            "pnl": position.get("realized_pnl"),
            "reason": reason,
            "reason_source": reason_source,
            "close_scope": "full",
            "update_time": position.get("closed_at"),
        })
    return history


def _infer_closed_position_reason(
    position: dict[str, Any], protection: list[dict[str, Any]] | None = None,
) -> tuple[str, str]:
    """Infer exchange-side TP/SL closes when bot exit metadata is absent."""
    close = _as_float(position.get("close_price", position.get("closePrice")))
    stop = _as_float(position.get("stop_loss", position.get("slPrice")))
    target = _as_float(position.get("take_profit", position.get("tpPrice")))
    side = str(position.get("side") or "").upper()
    protection = protection or []
    if stop <= 0:
        rows = [row for row in protection if row.get("role") == "stop_loss"]
        stop = _as_float(rows[-1].get("trigger_price")) if rows else 0.0
    if target <= 0:
        rows = [row for row in protection if str(row.get("role", "")).startswith("take_profit_")]
        prices = [_as_float(row.get("trigger_price")) for row in rows]
        prices = [price for price in prices if price > 0]
        if prices:
            target = min(prices) if side in {"SHORT", "SELL"} else max(prices)
    if close > 0:
        if side in {"SHORT", "SELL"}:
            if stop > 0 and close >= stop:
                return "stop_loss_hit", "price_inference"
            if target > 0 and close <= target:
                return "take_profit_hit", "price_inference"
        else:
            if stop > 0 and close <= stop:
                return "stop_loss_hit", "price_inference"
            if target > 0 and close >= target:
                return "take_profit_hit", "price_inference"
    return "exchange_closed_without_bot_reason", "exchange_lifecycle"


def _parse_iso_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _deduplicate_orders(orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the freshest copy of each exchange order ID."""
    by_key: dict[str, dict[str, Any]] = {}
    without_id: list[dict[str, Any]] = []
    for order in orders:
        order_id = str(order.get("order_id") or "")
        if not order_id:
            without_id.append(order)
            continue
        key = f"{order.get('exchange', '')}:{order_id}"
        current = by_key.get(key)
        if current is None or str(order.get("updated_at") or "") >= str(current.get("updated_at") or ""):
            by_key[key] = order
    return [*by_key.values(), *without_id]


def _normalize_bitunix_closed_position(row: dict[str, Any]) -> dict[str, Any]:
    # Bitunix has returned both realizedPNL and realizedPnl in different
    # endpoint/client versions. Preserve the sign for Overview win/loss KPI.
    realized = _as_float(
        row.get("realizedPNL", row.get("realizedPnl", row.get("realized_pnl")))
    )
    fee = _as_float(row.get("fee"))
    funding = _as_float(row.get("funding"))
    return {
        "exchange": "bitunix",
        "position_id": row.get("positionId"),
        "symbol": row.get("symbol"),
        "side": str(row.get("side") or "").upper(),
        "quantity": row.get("maxQty"),
        "entry_price": row.get("entryPrice"),
        "close_price": row.get("closePrice"),
        "stop_loss": row.get("stopLoss", row.get("slPrice")),
        "take_profit": row.get("takeProfit", row.get("tpPrice")),
        "leverage": row.get("leverage"),
        "margin_type": row.get("marginMode"),
        "realized_pnl": realized,
        "fee": fee,
        "funding": funding,
        "net_pnl": realized - fee + funding,
        "opened_at": _millis_to_iso(row.get("ctime")),
        "closed_at": _millis_to_iso(row.get("mtime")),
        "status": "CLOSED",
        "reason": "closed_position",
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


def _account_balance_usdt(
    exchange: str, result: dict[str, Any], details: dict[str, Any]
) -> float:
    if exchange == "bitunix":
        # Bitunix separates immediately available collateral, order-frozen
        # collateral, and position margin. All remain account funds.
        return _sum_numbers(
            result.get("available"), result.get("frozen"), result.get("margin")
        )
    return _available_usdt(exchange, result, details)


def _equity_usdt(
    exchange: str, result: dict[str, Any], details: dict[str, Any]
) -> float:
    balance = _account_balance_usdt(exchange, result, details)
    if exchange == "bitunix":
        return balance + _sum_numbers(
            result.get("cross_unrealized_pnl"),
            result.get("isolation_unrealized_pnl"),
        )
    return balance


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


def _millis_to_iso(value: object) -> str | None:
    try:
        millis = int(float(value or 0))
    except (TypeError, ValueError):
        return None
    if millis <= 0:
        return None
    from datetime import UTC, datetime

    return datetime.fromtimestamp(millis / 1000, tz=UTC).isoformat()


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
