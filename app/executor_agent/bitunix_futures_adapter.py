"""Bitunix USDⓈ-M Futures adapter for the Executor Agent.

Translates Executor Agent ``OrderRequest`` objects into Bitunix Futures API
payloads and submits them via the existing Bitunix auth scheme (two-pass
SHA256 signature). Live submission is gated by a three-toggle safety gate
identical in spirit to ``FuturesLiveSafetyGate`` for Binance Futures.

Scope
-----

- MARKET and LIMIT entry orders (BUY/SELL) via
  ``POST /api/v1/futures/trade/place_order``.
- LIMIT reduce-only orders (for partial TP style exits).
- STOP_MARKET / STOP_LIMIT are rejected with a clear reason because they
  require a position id in Bitunix. Handle those via a separate TP/SL
  workflow if you need them.

Safety
------

- ``BitunixLiveSafetyGate(enabled + dry_run + confirm_live)`` must all be
  True to hit the network. Otherwise every order is short-circuited into a
  ``REJECTED`` result.
- Adapter never bypasses the gate. Test / dry-run mode simply skips the
  HTTP call and returns a deterministic reject.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.executor_agent.models import (
    ExecutionResult,
    OrderRequest,
    OrderType,
)
from app.execution.lifecycle_contract import LIFECYCLE_VERSION, TP_ROLES


BITUNIX_FUTURES_BASE = "https://fapi.bitunix.com"
BITUNIX_USER_AGENT = "crypto-quant-bot/1.0 (+executor-agent)"
BITUNIX_PLACE_ORDER_PATH = "/api/v1/futures/trade/place_order"
BITUNIX_PENDING_ORDER_PATH = "/api/v1/futures/trade/get_pending_orders"
BITUNIX_CANCEL_ORDER_PATH = "/api/v1/futures/trade/cancel_order"
BITUNIX_HISTORY_ORDER_PATH = "/api/v1/futures/trade/get_history_orders"
BITUNIX_ACCOUNT_PATH = "/api/v1/futures/account"
BITUNIX_CHANGE_LEVERAGE_PATH = "/api/v1/futures/account/change_leverage"
BITUNIX_TPSL_PLACE_PATH = "/api/v1/futures/tpsl/place_order"
BITUNIX_TPSL_PENDING_PATH = "/api/v1/futures/tpsl/get_pending_orders"
BITUNIX_TPSL_MODIFY_PATH = "/api/v1/futures/tpsl/modify_order"
BITUNIX_TPSL_CANCEL_PATH = "/api/v1/futures/tpsl/cancel_order"
BITUNIX_OPENAPI_BLOCKLIST_PATH = Path("logs/bitunix_openapi_unsupported.json")
BITUNIX_PENDING_TP_PATH = Path("logs/bitunix_pending_take_profits.json")
TP_PROTECTION_TIMEOUT_SECONDS = 60
TP_MAX_PLACEMENT_ATTEMPTS = 3
TP_ORPHAN_PLAN_RETENTION_SECONDS = 3600
TP_PRICE_TOLERANCE = 1e-3
TP_QUANTITY_EPSILON = 1e-8
DEFAULT_TP_R_MULTIPLES = (2.0, 3.0, 4.0)
DEFAULT_TP_FRACTIONS = (0.3, 0.3, 0.4)
BITUNIX_ORDER_METADATA_PATH = Path("logs/bitunix_order_metadata.json")
BITUNIX_MIN_AMOUNT_PATH = Path("logs/bitunix_min_amounts.json")
TP1_TRAILING_STRATEGY = "tp1_partial_trailing_v1"
SUPPORTED_TP_STRATEGIES = {TP1_TRAILING_STRATEGY, LIFECYCLE_VERSION}
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BitunixLiveSafetyGate:
    """Three-toggle gate — all must be True for real submission."""

    enabled: bool = False
    dry_run: bool = True
    confirm_live: bool = False

    def evaluate(self) -> str | None:
        if not self.enabled:
            return "safety_gate_disabled"
        if self.dry_run:
            return "safety_gate_dry_run"
        if not self.confirm_live:
            return "safety_gate_confirm_required"
        return None


@dataclass(frozen=True)
class BitunixCredentials:
    api_key: str
    api_secret: str

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.api_secret)


class BitunixFuturesExecutorAdapter:
    """Adapter between Executor Agent and Bitunix Futures REST API.

    The adapter is stateless. HTTP transport is injectable so tests never
    hit the network. Safety gate is enforced before any request.
    """

    def __init__(
        self,
        credentials: BitunixCredentials,
        *,
        safety_gate: BitunixLiveSafetyGate | None = None,
        base_url: str = BITUNIX_FUTURES_BASE,
        transport: Any = None,
        query_transport: Any = None,
        leverage: int | None = None,
        blocked_entry_symbols: set[str] | None = None,
        pending_tp_path: Path | None = None,
        min_amount_path: Path | None = None,
        order_metadata_path: Path | None = None,
        lifecycle_store_path: Path | None = None,
    ) -> None:
        self._credentials = credentials
        self._safety_gate = safety_gate or BitunixLiveSafetyGate()
        self._base_url = base_url.rstrip("/")
        self._transport = transport  # optional callable(url, headers, body) -> dict
        self._query_transport = query_transport
        self._leverage = int(leverage) if leverage is not None else None
        self._pending_tp_path = pending_tp_path or BITUNIX_PENDING_TP_PATH
        self._min_amount_path = min_amount_path or (
            pending_tp_path.with_name("bitunix_min_amounts.json")
            if pending_tp_path is not None else BITUNIX_MIN_AMOUNT_PATH
        )
        self._minimum_amounts = self._load_minimum_amounts()
        self._lifecycle_store_path = lifecycle_store_path or (
            pending_tp_path.with_name("bitunix_live_lifecycle.json")
            if pending_tp_path is not None else Path("logs/bitunix_live_lifecycle.json")
        )
        self._order_metadata_path = order_metadata_path or (
            pending_tp_path.with_name("bitunix_order_metadata.json")
            if pending_tp_path is not None
            else BITUNIX_ORDER_METADATA_PATH
            if transport is None
            else None
        )
        self._blocked_entry_symbols = {
            _canonical_symbol(symbol) for symbol in (blocked_entry_symbols or set())
        }

    def place_order(
        self,
        order: OrderRequest,
        *,
        timestamp: str,
    ) -> ExecutionResult:
        gate_block = self._safety_gate.evaluate()
        if gate_block is not None:
            return self._reject(order, timestamp, gate_block)

        if not self._credentials.configured:
            return self._reject(order, timestamp, "credentials_missing")

        try:
            body = self._build_body(order)
        except ValueError as exc:
            return self._reject(order, timestamp, f"invalid_request: {exc}")

        headers = self._sign_headers(body_json=json.dumps(body, separators=(",", ":")))
        url = f"{self._base_url}{BITUNIX_PLACE_ORDER_PATH}"

        try:
            payload = self._send(url=url, headers=headers, body=body)
        except Exception as exc:  # noqa: BLE001
            return self._reject(order, timestamp, f"http_error: {exc}")

        return self._to_execution_result(payload, order, timestamp)

    def pending_orders(self, *, symbol: str | None = None) -> list[dict[str, Any]]:
        """Return open entry orders from Bitunix trade API."""
        params = {"symbol": symbol.replace("/", "").replace("-", "").upper()} if symbol else {}
        payload = self._private_get(BITUNIX_PENDING_ORDER_PATH, params)
        data = payload.get("data")
        if isinstance(data, dict):
            for key in ("orderList", "orders", "list"):
                rows = data.get(key)
                if isinstance(rows, list):
                    return [dict(row) for row in rows if isinstance(row, dict)]
        if isinstance(data, list):
            return [dict(row) for row in data if isinstance(row, dict)]
        return []

    def history_orders(
        self, *, symbol: str | None = None, limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return recent exchange orders, including filled partial exits."""
        params: dict[str, Any] = {"limit": max(1, int(limit))}
        if symbol:
            params["symbol"] = symbol.replace("/", "").replace("-", "").upper()
        payload = self._private_get(BITUNIX_HISTORY_ORDER_PATH, params)
        data = payload.get("data")
        if isinstance(data, dict):
            for key in ("orderList", "orders", "list"):
                rows = data.get(key)
                if isinstance(rows, list):
                    return [dict(row) for row in rows if isinstance(row, dict)]
        if isinstance(data, list):
            return [dict(row) for row in data if isinstance(row, dict)]
        return []

    def cancel_order(self, *, symbol: str, order_id: str) -> bool:
        """Cancel an unfilled entry order and verify it is no longer pending."""
        gate_block = self._safety_gate.evaluate()
        if gate_block is not None:
            raise RuntimeError(gate_block)
        body = {
            "symbol": symbol.replace("/", "").replace("-", "").upper(),
            "orderId": str(order_id),
        }
        self._post_success(BITUNIX_CANCEL_ORDER_PATH, body)
        still_pending = any(
            str(row.get("orderId") or row.get("order_id") or row.get("id")) == str(order_id)
            for row in self.pending_orders(symbol=symbol)
        )
        if still_pending:
            raise RuntimeError("entry_cancel_not_confirmed")
        return True

    def order_metadata(self, order_id: str) -> dict[str, Any]:
        """Return bot-owned metadata for one exchange order."""
        if self._order_metadata_path is None:
            return {}
        try:
            payload = json.loads(self._order_metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        rows = payload.get("orders") if isinstance(payload, dict) else None
        row = rows.get(str(order_id)) if isinstance(rows, dict) else None
        return dict(row) if isinstance(row, dict) else {}

    def available_balance(self, margin_coin: str = "USDT") -> float:
        """Read available futures balance for live sizing preflight."""

        if not self._credentials.configured:
            raise RuntimeError("credentials_missing")
        params = {"marginCoin": margin_coin.upper()}
        canonical = "".join(f"{key}{params[key]}" for key in sorted(params))
        nonce = secrets.token_hex(16)
        timestamp = str(int(time.time() * 1000))
        digest = hashlib.sha256(
            f"{nonce}{timestamp}{self._credentials.api_key}{canonical}".encode("utf-8")
        ).hexdigest()
        signature = hashlib.sha256(
            f"{digest}{self._credentials.api_secret}".encode("utf-8")
        ).hexdigest()
        request = urllib.request.Request(
            f"{self._base_url}{BITUNIX_ACCOUNT_PATH}?{urllib.parse.urlencode(params)}",
            headers={
                "api-key": self._credentials.api_key,
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
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"account_preflight_failed: {exc}") from exc
        if not isinstance(payload, dict) or payload.get("code") != 0:
            raise RuntimeError(str(payload.get("msg") if isinstance(payload, dict) else "invalid_response"))
        data = payload.get("data") or {}
        if isinstance(data, list):
            data = data[0] if data and isinstance(data[0], dict) else {}
        if not isinstance(data, dict):
            raise RuntimeError("invalid_account_payload")
        available = _float(data.get("available"))
        if available <= 0:
            raise RuntimeError("available_balance_not_positive")
        return available

    def pending_tpsl(
        self, *, symbol: str | None = None, position_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Read authoritative pending TP/SL orders from Bitunix."""

        if not self._credentials.configured:
            raise RuntimeError("credentials_missing")
        # Unit transports that only capture POSTs intentionally do not expose
        # a private GET endpoint. Live adapters always use the real query path.
        if self._query_transport is None and self._transport is not None:
            return []
        params: dict[str, Any] = {"limit": max(1, min(int(limit), 1000))}
        if symbol:
            params["symbol"] = symbol.replace("/", "").replace("-", "").upper()
        if position_id:
            params["positionId"] = str(position_id)
        payload = self._private_get(BITUNIX_TPSL_PENDING_PATH, params)
        data = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(data, list):
            rows = [dict(row) for row in data if isinstance(row, dict)]
            return self._filter_tpsl_rows(
                rows, symbol=symbol, position_id=position_id,
            )
        if isinstance(data, dict):
            for key in ("orderList", "orders", "list"):
                rows = data.get(key)
                if isinstance(rows, list):
                    return self._filter_tpsl_rows(
                        [dict(row) for row in rows if isinstance(row, dict)],
                        symbol=symbol, position_id=position_id,
                    )
        return []

    @staticmethod
    def _filter_tpsl_rows(
        rows: list[dict[str, Any]], *, symbol: str | None, position_id: str | None,
    ) -> list[dict[str, Any]]:
        compact = _canonical_symbol(symbol) if symbol else ""
        return [
            row for row in rows
            if (
                not position_id
                or not str(row.get("positionId") or row.get("position_id") or "")
                or str(row.get("positionId") or row.get("position_id")) == str(position_id)
            )
            and (
                not compact
                or _canonical_symbol(row.get("symbol")) == compact
            )
        ]

    def modify_tpsl_order(
        self,
        *,
        order_id: str,
        stop_price: float | None = None,
        stop_quantity: float | None = None,
        take_profit_price: float | None = None,
        take_profit_quantity: float | None = None,
    ) -> dict[str, Any]:
        """Modify one TP/SL in place and verify its authoritative state."""

        gate_block = self._safety_gate.evaluate()
        if gate_block is not None:
            raise RuntimeError(gate_block)
        body: dict[str, Any] = {"orderId": str(order_id)}
        if stop_price is not None:
            body.update({
                "slPrice": _fmt_number(stop_price), "slStopType": "MARK_PRICE",
                "slOrderType": "MARKET",
            })
        if stop_quantity is not None:
            body["slQty"] = _fmt_number(stop_quantity)
        if take_profit_price is not None:
            body.update({
                "tpPrice": _fmt_number(take_profit_price), "tpStopType": "MARK_PRICE",
                "tpOrderType": "MARKET",
            })
        if take_profit_quantity is not None:
            body["tpQty"] = _fmt_number(take_profit_quantity)
        if len(body) == 1:
            raise ValueError("tpsl_modify_requires_price_or_quantity")
        self._post_success(BITUNIX_TPSL_MODIFY_PATH, body)
        matches = [row for row in self.pending_tpsl() if str(row.get("id")) == str(order_id)]
        if len(matches) != 1:
            raise RuntimeError("tpsl_modify_not_confirmed")
        row = matches[0]
        expected = {
            "slPrice": stop_price, "slQty": stop_quantity,
            "tpPrice": take_profit_price, "tpQty": take_profit_quantity,
        }
        for field, value in expected.items():
            if value is not None and abs(_float(row.get(field)) - float(value)) > 1e-8:
                raise RuntimeError(f"tpsl_modify_mismatch:{field}")
        return row

    def cancel_tpsl_order(self, *, symbol: str, order_id: str) -> bool:
        """Cancel a TP/SL and confirm it disappeared from pending orders."""

        gate_block = self._safety_gate.evaluate()
        if gate_block is not None:
            raise RuntimeError(gate_block)
        body = {
            "symbol": symbol.replace("/", "").replace("-", "").upper(),
            "orderId": str(order_id),
        }
        self._post_success(BITUNIX_TPSL_CANCEL_PATH, body)
        still_pending = any(
            str(row.get("id")) == str(order_id)
            for row in self.pending_tpsl(symbol=symbol)
        )
        if still_pending:
            raise RuntimeError("tpsl_cancel_not_confirmed")
        return True

    def tighten_stop(
        self, *, symbol: str, position_id: str, side: str, new_stop: float,
        quantity: float,
    ) -> dict[str, Any]:
        """Tighten the single live SL; never cancel it or widen risk."""

        rows = self.pending_tpsl(symbol=symbol, position_id=position_id)
        stops = [row for row in rows if _float(row.get("slPrice")) > 0]
        if len(stops) != 1:
            raise RuntimeError("exactly_one_live_stop_required")
        current = _float(stops[0].get("slPrice"))
        is_short = _canonical_position_side(side) == "SHORT"
        if new_stop <= 0 or (is_short and new_stop >= current) or (not is_short and new_stop <= current):
            raise ValueError("stop_update_must_tighten_risk")
        result = self.modify_tpsl_order(
            order_id=str(stops[0]["id"]), stop_price=new_stop,
            stop_quantity=quantity,
        )
        self._record_order_metadata(
            f"protection:{position_id}:stop_loss",
            OrderRequest(
                symbol=symbol, side="BUY" if _canonical_position_side(side) == "SHORT" else "SELL",
                order_type="STOP", quantity=quantity, price=new_stop,
                reduce_only=True,
                meta={
                    "role": "stop_loss",
                    "reason": "trailing_stop",
                    "metadata_kind": "protection_intent",
                    "position_id": str(position_id),
                    "trigger_price": new_stop,
                },
            ),
            datetime.now(tz=UTC).isoformat(),
        )
        return result

    def place_lifecycle_take_profit(
        self, *, symbol: str, position_id: str, side: str, role: str,
        price: float, quantity: float,
    ) -> ExecutionResult:
        if role not in TP_ROLES:
            raise ValueError("invalid_take_profit_role")
        order = OrderRequest(
            symbol=symbol, side=str(side).upper(), order_type="LIMIT",
            quantity=float(quantity), price=float(price), reduce_only=True,
            meta={
                "role": role, "position_id": str(position_id),
                "lifecycle_version": LIFECYCLE_VERSION,
            },
        )
        return self._place_take_profit(
            order, str(position_id), datetime.now(tz=UTC).isoformat(),
        )

    def place_orders(
        self, orders: list[OrderRequest], *, timestamp: str,
    ) -> list[ExecutionResult]:
        """Submit a complete plan, attaching protection atomically to entries."""

        if not orders:
            return []
        entry = next((item for item in orders if item.meta.get("role") == "entry"), None)
        if entry is None:
            return [self.place_order(item, timestamp=timestamp) for item in orders]

        gate_block = self._safety_gate.evaluate()
        if gate_block is not None:
            return [self._reject(item, timestamp, gate_block) for item in orders]
        if not self._credentials.configured:
            return [self._reject(item, timestamp, "credentials_missing") for item in orders]
        if _canonical_symbol(entry.symbol) in self._blocked_entry_symbols:
            return [
                self._reject(item, timestamp, "pending_entry_exists") for item in orders
            ]

        stop = next((item for item in orders if item.meta.get("role") == "stop_loss"), None)
        take_profits = [
            item for item in orders
            if item.meta.get("role") in TP_ROLES
        ]
        if stop is None or stop.stop_price is None or stop.stop_price <= 0:
            return [
                self._reject(item, timestamp, "protective_stop_required_before_live_entry")
                for item in orders
            ]
        if not take_profits or any(item.price is None or item.price <= 0 for item in take_profits):
            return [
                self._reject(item, timestamp, "take_profit_required_before_live_entry")
                for item in orders
            ]

        if self._leverage is not None:
            leverage_error = self.change_leverage(entry.symbol, self._leverage)
            if leverage_error is not None:
                return [
                    self._reject(item, timestamp, f"change_leverage_failed: {leverage_error}")
                    for item in orders
                ]

        try:
            body = self._build_body(entry)
            body.update({
                "slPrice": _fmt_number(stop.stop_price),
                "slStopType": "MARK",
                "slOrderType": "MARKET",
            })
        except ValueError as exc:
            return [self._reject(item, timestamp, f"invalid_request: {exc}") for item in orders]

        headers = self._sign_headers(body_json=json.dumps(body, separators=(",", ":")))
        try:
            payload = self._send(
                url=f"{self._base_url}{BITUNIX_PLACE_ORDER_PATH}",
                headers=headers,
                body=body,
            )
        except Exception as exc:  # noqa: BLE001
            return [self._reject(item, timestamp, f"http_error: {exc}") for item in orders]

        entry_result = self._to_execution_result(payload, entry, timestamp)
        if entry_result.status != "REJECTED":
            self._queue_take_profits(
                entry, stop, take_profits, entry_result.order_id,
            )
        attached_items = {id(stop)}
        protective_results: list[ExecutionResult] = []
        for item in orders:
            if item is entry:
                continue

            attached = id(item) in attached_items
            accepted = entry_result.status != "REJECTED"
            if not accepted:
                status = "REJECTED"
                reason = entry_result.reason
            elif attached:
                status = "SUBMITTED"
                reason = "attached_to_entry"
            else:
                status = "PENDING"
                reason = "queued_until_position_id_available"

            protective_results.append(ExecutionResult(
                status=status,
                order_id=entry_result.order_id if attached else "",
                symbol=item.symbol, side=item.side, order_type=item.order_type,
                requested_quantity=item.quantity, filled_quantity=0.0,
                average_price=0.0, timestamp=timestamp,
                reason=reason,
                meta={
                    **item.meta,
                    "attached_to_entry": attached,
                    "exchange_order_created": bool(accepted and attached),
                },
            ))
        return [entry_result, *protective_results]

    def reconcile_take_profits(
        self, positions: list[dict[str, Any]], *, timestamp: str,
    ) -> list[ExecutionResult]:
        """Create queued lifecycle TPs after Bitunix exposes a positionId."""

        pending = self._load_pending_take_profits()
        if not pending:
            return []
        by_symbol: dict[str, list[dict[str, Any]]] = {}
        for position in positions:
            symbol = _canonical_symbol(position.get("symbol"))
            if symbol:
                by_symbol.setdefault(symbol, []).append(position)

        results: list[ExecutionResult] = []
        remaining: list[dict[str, Any]] = []
        # Repeated scanner decisions can queue several plans before Bitunix
        # exposes the positionId. For one aggregated exchange position only the
        # newest matching TP1 plan is valid; submitting every queued copy would
        # create multiple exits for the same position.
        newest_matching_index: dict[tuple[str, str], int] = {}
        for index, plan in enumerate(pending):
            if plan.get("strategy") not in SUPPORTED_TP_STRATEGIES:
                continue
            key = (
                _canonical_symbol(plan.get("symbol")),
                str(plan.get("position_side") or "").upper(),
            )
            candidates = by_symbol.get(key[0], [])
            if any(
                not key[1]
                or _canonical_position_side(row.get("side")) == key[1]
                for row in candidates
            ):
                newest_matching_index[key] = index

        for plan_index, plan in enumerate(pending):
            # Unknown legacy plans cannot be safely joined to an aggregated
            # position by symbol alone. Preserve them for audit.
            if plan.get("strategy") not in SUPPORTED_TP_STRATEGIES:
                remaining.append(plan)
                continue
            symbol = _canonical_symbol(plan.get("symbol"))
            expected_side = str(plan.get("position_side") or "").upper()
            plan_key = (symbol, expected_side)
            candidates = by_symbol.get(symbol, [])
            position = next((
                row for row in candidates
                if not expected_side or _canonical_position_side(row.get("side")) == expected_side
            ), None)
            if position is None:
                logger.warning(
                    "Bitunix TP reconciliation deferred symbol=%s side=%s "
                    "entry_order_id=%s reason=position_not_found",
                    symbol, expected_side, plan.get("entry_order_id"),
                )
                if not self._orphan_plan_expired(plan, timestamp):
                    remaining.append(plan)
                else:
                    logger.info(
                        "Bitunix TP plan pruned symbol=%s side=%s "
                        "entry_order_id=%s reason=orphan_plan_expired",
                        symbol, expected_side, plan.get("entry_order_id"),
                    )
                continue
            if newest_matching_index.get(plan_key) != plan_index:
                # Stale duplicate for the currently active position. Drop it;
                # only the latest plan below may create an exchange-side TP.
                continue
            position_id = str(position.get("position_id") or "")
            if not position_id:
                logger.warning(
                    "Bitunix TP reconciliation deferred symbol=%s side=%s "
                    "entry_order_id=%s reason=position_id_missing",
                    symbol, expected_side, plan.get("entry_order_id"),
                )
                remaining.append(plan)
                continue
            if self._tp_plan_expired(plan, timestamp):
                self._blocked_entry_symbols.add(symbol)
                logger.error(
                    "Bitunix TP protection requires manual action symbol=%s position_id=%s",
                    symbol, position_id,
                )
                remaining.append({
                    **plan,
                    "last_protection_alert_at": timestamp,
                    "protection_status": "manual_action_required",
                })
                continue
            queued = [
                dict(raw) for raw in plan.get("take_profits", [])
                if isinstance(raw, dict) and raw.get("role") in TP_ROLES
            ]
            try:
                active_tpsl = self.pending_tpsl(
                    symbol=symbol, position_id=position_id,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Bitunix TP reconciliation deferred symbol=%s "
                    "position_id=%s reason=protection_check_failed error=%s",
                    symbol, position_id, exc,
                )
                remaining.append(plan)
                continue

            def _price_matches(actual: float, expected: float) -> bool:
                return abs(actual - expected) <= max(
                    TP_QUANTITY_EPSILON, abs(expected) * TP_PRICE_TOLERANCE,
                )

            def _covered_quantity(raw: dict[str, Any]) -> float:
                expected_price = _float(raw.get("price"))
                return sum(
                    _float(row.get("tpQty", row.get("qty", row.get("takeProfitQty"))))
                    for row in active_tpsl
                    if _float(row.get("tpPrice", row.get("takeProfitPrice"))) > 0
                    and _price_matches(
                        _float(row.get("tpPrice", row.get("takeProfitPrice"))),
                        expected_price,
                    )
                )

            minimum_amount = self._minimum_amounts.get(symbol, 0.0)
            incomplete: list[dict[str, Any]] = []
            for raw in queued:
                if minimum_amount and _float(raw.get("quantity")) <= minimum_amount:
                    continue
                shortfall = _float(raw.get("quantity")) - _covered_quantity(raw)
                if shortfall > TP_QUANTITY_EPSILON:
                    incomplete.append({**raw, "quantity": shortfall})
            queued = incomplete
            if not queued:
                # All planned levels are confirmed for this exact position.
                if plan.get("strategy") == LIFECYCLE_VERSION:
                    self._register_live_lifecycle(plan, position, plan.get("take_profits", []))
                continue
            attempts = int(plan.get("tp_placement_attempts", 0))
            if attempts >= TP_MAX_PLACEMENT_ATTEMPTS:
                self._blocked_entry_symbols.add(symbol)
                remaining.append({
                    **plan,
                    "protection_status": "protection_failed",
                    "last_protection_failure_at": timestamp,
                })
                logger.error(
                    "Bitunix TP placement retry cap reached symbol=%s position_id=%s",
                    symbol, position_id,
                )
                continue
            unsent: list[dict[str, Any]] = []
            placed_any = False
            permanent_rejection = False
            for index, raw in enumerate(queued):
                price = float(raw["price"])
                target_rr = _float(raw.get("target_risk_reward"))
                entry_price = _float(
                    position.get("entry_price", position.get("entry"))
                )
                stop_loss = _float(position.get("stop_loss"))
                if target_rr > 0 and entry_price > 0 and stop_loss > 0:
                    risk_distance = abs(entry_price - stop_loss)
                    price = (
                        entry_price + (target_rr * risk_distance)
                        if expected_side == "LONG"
                        else entry_price - (target_rr * risk_distance)
                    )
                order = OrderRequest(
                    symbol=symbol,
                    side=str(raw["side"]).upper(),
                    order_type="LIMIT",
                    quantity=float(raw["quantity"]),
                    price=price,
                    reduce_only=True,
                    meta={
                        "role": raw["role"], "position_id": position_id,
                        "lifecycle_version": plan.get("lifecycle_version"),
                        "target_risk_reward": target_rr or None,
                        "tp_level_source": (
                            "configured_rr_exchange_fill"
                            if target_rr > 0 and entry_price > 0 and stop_loss > 0
                            else "decision_plan"
                        ),
                    },
                )
                result = self._place_take_profit(order, position_id, timestamp)
                results.append(result)
                placed_any = True
                if result.status == "REJECTED":
                    logger.error(
                        "Bitunix TP placement rejected symbol=%s position_id=%s "
                        "role=%s reason=%s raw=%s",
                        symbol, position_id, raw.get("role"), result.reason,
                        result.meta.get("raw"),
                    )
                    # Keep only the failed TP and later levels. Earlier levels
                    # were accepted and must not be duplicated on the next scan.
                    permanent_rejection = _is_minimum_amount_rejection(result)
                    if permanent_rejection:
                        self._remember_minimum_amount(symbol, float(raw["quantity"]))
                    unsent = queued[index:]
                    break
            if unsent:
                if permanent_rejection:
                    unsent = queued[index + 1:]
                remaining.append({
                    **plan, "take_profits": unsent,
                    "tp_placement_attempts": attempts + (
                        1 if placed_any and not permanent_rejection else 0
                    ),
                })
            elif plan.get("strategy") == LIFECYCLE_VERSION and not permanent_rejection:
                self._register_live_lifecycle(plan, position, queued)
        self._save_pending_take_profits(remaining)
        return results

    def repair_unprotected_positions(
        self, positions: list[dict[str, Any]], *, timestamp: str,
    ) -> list[ExecutionResult]:
        """Repair open positions that have an SL but no exchange-side TP."""
        results: list[ExecutionResult] = []
        for position in positions:
            symbol = _canonical_symbol(position.get("symbol"))
            position_id = str(position.get("position_id") or position.get("positionId") or "")
            entry = _float(position.get("entry_price", position.get("entry")))
            stop = _float(position.get("stop_loss", position.get("stopLoss")))
            quantity = _float(position.get("quantity", position.get("qty")))
            side = _canonical_position_side(position.get("side"))
            if not symbol or not position_id or entry <= 0 or stop <= 0 or quantity <= 0 or side not in {"LONG", "SHORT"}:
                continue
            try:
                active = self.pending_tpsl(symbol=symbol, position_id=position_id)
            except Exception as exc:  # noqa: BLE001
                self._blocked_entry_symbols.add(symbol)
                logger.error("Bitunix TP repair read failed symbol=%s error=%s", symbol, exc)
                continue
            risk = abs(entry - stop)
            direction = 1.0 if side == "LONG" else -1.0
            exit_side = "SELL" if side == "LONG" else "BUY"
            quantities = [quantity * fraction for fraction in DEFAULT_TP_FRACTIONS]
            has_existing_tp = any(
                _float(row.get("tpPrice", row.get("takeProfitPrice"))) > 0
                for row in active
            )
            def _price_matches(actual: float, expected: float) -> bool:
                return abs(actual - expected) <= max(
                    TP_QUANTITY_EPSILON, abs(expected) * TP_PRICE_TOLERANCE,
                )

            def _covered(expected_price: float) -> float:
                return sum(
                    _float(row.get("tpQty", row.get("qty", row.get("takeProfitQty"))))
                    for row in active
                    if _float(row.get("tpPrice", row.get("takeProfitPrice"))) > 0
                    and _price_matches(
                        _float(row.get("tpPrice", row.get("takeProfitPrice"))),
                        expected_price,
                    )
                )

            minimum_amount = self._minimum_amounts.get(symbol, 0.0)

            failed = False
            permanent_min_rejection = False
            submitted_for_position = False
            for index, (multiple, tp_quantity) in enumerate(zip(DEFAULT_TP_R_MULTIPLES, quantities)):
                tp_price = round(entry + direction * risk * multiple, 8)
                tp_quantity = max(0.0, tp_quantity - _covered(tp_price))
                if tp_quantity <= TP_QUANTITY_EPSILON:
                    continue
                if has_existing_tp and tp_quantity <= minimum_amount:
                    continue
                order = OrderRequest(
                    symbol=symbol, side=exit_side, order_type="LIMIT",
                    quantity=tp_quantity, price=tp_price,
                    reduce_only=True,
                    meta={"role": TP_ROLES[index], "position_id": position_id, "repair": True,
                          "target_risk_reward": multiple},
                )
                result = self._place_take_profit(order, position_id, timestamp)
                results.append(result)
                if result.status == "REJECTED":
                    if _is_minimum_amount_rejection(result):
                        permanent_min_rejection = True
                        self._remember_minimum_amount(symbol, tp_quantity)
                    logger.error(
                        "Bitunix TP repair rejected symbol=%s position_id=%s "
                        "role=%s reason=%s raw=%s",
                        symbol, position_id, TP_ROLES[index], result.reason,
                        result.meta.get("raw"),
                    )
                    failed = True
                    break
                submitted_for_position = True
            if failed and not submitted_for_position and not has_existing_tp:
                fallback_price = round(entry + direction * risk * DEFAULT_TP_R_MULTIPLES[0], 8)
                fallback_covered = _covered(fallback_price)
                fallback_quantity = max(0.0, quantity - fallback_covered)
                if fallback_quantity <= TP_QUANTITY_EPSILON:
                    continue
                fallback = OrderRequest(
                    symbol=symbol, side=exit_side, order_type="LIMIT",
                    quantity=fallback_quantity, price=fallback_price, reduce_only=True,
                    meta={
                        "role": "take_profit_1", "position_id": position_id,
                        "repair": True, "repair_fallback": "single_full_quantity",
                        "target_risk_reward": DEFAULT_TP_R_MULTIPLES[0],
                    },
                )
                fallback_result = self._place_take_profit(fallback, position_id, timestamp)
                results.append(fallback_result)
                if _is_minimum_amount_rejection(fallback_result):
                    permanent_min_rejection = True
                    self._remember_minimum_amount(symbol, fallback_quantity)
                failed = fallback_result.status == "REJECTED"
            if failed and not permanent_min_rejection:
                self._blocked_entry_symbols.add(symbol)
                logger.error("Bitunix TP repair failed symbol=%s position_id=%s", symbol, position_id)
            else:
                logger.info("Bitunix TP repair submitted symbol=%s position_id=%s", symbol, position_id)
        return results

    @staticmethod
    def _tp_plan_expired(plan: dict[str, Any], timestamp: str) -> bool:
        created = str(plan.get("created_at") or "")
        if not created:
            return False
        try:
            started = datetime.fromisoformat(created.replace("Z", "+00:00"))
            current = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            return False
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        return (current - started).total_seconds() >= TP_PROTECTION_TIMEOUT_SECONDS

    @staticmethod
    def _orphan_plan_expired(plan: dict[str, Any], timestamp: str) -> bool:
        created = str(plan.get("created_at") or "")
        if not created:
            return False
        try:
            started = datetime.fromisoformat(created.replace("Z", "+00:00"))
            current = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            return False
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        return (current - started).total_seconds() >= TP_ORPHAN_PLAN_RETENTION_SECONDS

    def _emergency_close_unprotected(
        self, position: dict[str, Any], *, symbol: str,
        position_id: str, timestamp: str,
    ) -> ExecutionResult:
        side = "SELL" if _canonical_position_side(position.get("side")) == "LONG" else "BUY"
        quantity = _float(position.get("quantity", position.get("qty")))
        order = OrderRequest(
            symbol=symbol, side=side, order_type="MARKET", quantity=quantity,
            reduce_only=True,
            meta={
                "role": "emergency_tp_protection_close",
                "position_id": position_id,
                "reason": "take_profit_timeout",
            },
        )
        if quantity <= 0:
            return self._reject(order, timestamp, "emergency_close_quantity_missing")
        return self.place_order(order, timestamp=timestamp)

    def _place_take_profit(
        self, order: OrderRequest, position_id: str, timestamp: str,
    ) -> ExecutionResult:
        gate_block = self._safety_gate.evaluate()
        if gate_block is not None:
            return self._reject(order, timestamp, gate_block)
        body = {
            "symbol": order.symbol.replace("/", "").upper(),
            "positionId": position_id,
            "tpPrice": _fmt_number(float(order.price or 0.0)),
            "tpStopType": "MARK_PRICE",
            "tpOrderType": "MARKET",
            "tpQty": _fmt_number(order.quantity),
        }
        headers = self._sign_headers(body_json=json.dumps(body, separators=(",", ":")))
        try:
            payload = self._send(
                url=f"{self._base_url}{BITUNIX_TPSL_PLACE_PATH}",
                headers=headers, body=body,
            )
        except Exception as exc:  # noqa: BLE001
            return self._reject(order, timestamp, f"http_error: {exc}")
        return self._to_execution_result(payload, order, timestamp)

    def _queue_take_profits(
        self, entry: OrderRequest, stop: OrderRequest,
        take_profits: list[OrderRequest], order_id: str,
    ) -> None:
        plans = self._load_pending_take_profits()
        key = str(order_id or entry.meta.get("client_order_id") or "")
        if key and any(str(item.get("entry_order_id")) == key for item in plans):
            return
        plans.append({
            "entry_order_id": key,
            "symbol": _canonical_symbol(entry.symbol),
            "position_side": "LONG" if entry.side == "BUY" else "SHORT",
            "strategy": str(entry.meta.get("lifecycle_version") or LIFECYCLE_VERSION),
            "lifecycle_version": str(
                entry.meta.get("lifecycle_version") or LIFECYCLE_VERSION
            ),
            "initial_quantity": entry.quantity,
            "initial_stop": stop.stop_price,
            "reference_entry": entry.meta.get("reference_price"),
            "strategy_version": entry.meta.get("strategy_version"),
            "created_at": datetime.now(tz=UTC).isoformat(),
            "protection_status": "tp_pending",
            "emergency_close_attempts": 0,
            "tp_levels": [float(item.price) for item in take_profits if item.price],
            "take_profits": [{
                "role": str(item.meta.get("role")), "side": item.side,
                "quantity": item.quantity, "price": item.price,
                "target_risk_reward": item.meta.get("target_risk_reward"),
            } for item in take_profits],
        })
        self._save_pending_take_profits(plans)

    def _register_live_lifecycle(
        self, plan: dict[str, Any], position: dict[str, Any],
        take_profits: list[dict[str, Any]],
    ) -> None:
        """Register only a fully reconciled lifecycle-v1 exchange position."""

        from app.execution.live_lifecycle import (
            LiveLifecycleController, LiveLifecycleState, LiveLifecycleStore,
        )

        position_id = str(position.get("position_id") or "")
        entry = _float(position.get("entry_price", position.get("entry")))
        if not position_id or entry <= 0:
            raise RuntimeError("lifecycle_registration_requires_exchange_fill")
        initial_quantity = _float(plan.get("initial_quantity"))
        remaining = _float(position.get("quantity", position.get("remaining_size")))
        stop = _float(position.get("stop_loss")) or _float(plan.get("initial_stop"))
        raw_levels = plan.get("tp_levels")
        levels = (
            [float(value) for value in raw_levels if _float(value) > 0]
            if isinstance(raw_levels, list)
            else [float(row["price"]) for row in take_profits if _float(row.get("price")) > 0]
        )
        if initial_quantity <= 0 or remaining <= 0 or stop <= 0 or len(levels) != 3:
            raise RuntimeError("incomplete_lifecycle_registration_plan")
        LiveLifecycleController(
            self, LiveLifecycleStore(self._lifecycle_store_path),
        ).register(LiveLifecycleState(
            position_id=position_id,
            symbol=_canonical_symbol(plan.get("symbol")),
            side=str(plan.get("position_side") or ""),
            entry_price=entry,
            initial_stop=stop,
            current_stop=stop,
            initial_quantity=initial_quantity,
            remaining_quantity=remaining,
            tp_levels=levels,
            strategy_version=(
                dict(plan["strategy_version"])
                if isinstance(plan.get("strategy_version"), dict) else None
            ),
        ))
        self.record_protection_metadata(
            symbol=str(plan.get("symbol") or ""), position_id=position_id,
            side=str(plan.get("position_side") or ""), role="stop_loss",
            trigger_price=stop,
        )
        for index, price in enumerate(levels, start=1):
            self.record_protection_metadata(
                symbol=str(plan.get("symbol") or ""), position_id=position_id,
                side=str(plan.get("position_side") or ""),
                role=f"take_profit_{index}", trigger_price=price,
            )

    def record_protection_metadata(
        self, *, symbol: str, position_id: str, side: str,
        role: str, trigger_price: float | None = None,
    ) -> None:
        """Persist exchange-side protection intent for later reason inference."""
        if role not in {"stop_loss", *TP_ROLES} or not position_id:
            return
        order = OrderRequest(
            symbol=symbol,
            side="SELL" if str(side).upper() == "LONG" else "BUY",
            order_type="LIMIT", quantity=0.0, price=trigger_price,
            reduce_only=True,
            meta={
                "role": role,
                "metadata_kind": "protection_intent",
                "reason": "stop_loss",
                "position_id": str(position_id),
                "trigger_price": trigger_price,
            },
        )
        self._record_order_metadata(
            f"protection:{position_id}:{role}", order,
            datetime.now(tz=UTC).isoformat(),
        )

    def record_protection_metadata(
        self, *, symbol: str, position_id: str, side: str,
        role: str, trigger_price: float | None = None,
    ) -> None:
        """Persist exchange-side protection intent for later reason inference."""
        if role not in {"stop_loss", *TP_ROLES} or not position_id:
            return
        order = OrderRequest(
            symbol=symbol,
            side="SELL" if str(side).upper() == "LONG" else "BUY",
            order_type="LIMIT", quantity=0.0, price=trigger_price,
            reduce_only=True,
            meta={
                "role": role,
                "metadata_kind": "protection_intent",
                "reason": "stop_loss" if role == "stop_loss" else role,
                "position_id": str(position_id),
                "trigger_price": trigger_price,
            },
        )
        self._record_order_metadata(
            f"protection:{position_id}:{role}", order,
            datetime.now(tz=UTC).isoformat(),
        )

    def _load_pending_take_profits(self) -> list[dict[str, Any]]:
        try:
            payload = json.loads(self._pending_tp_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        rows = payload.get("plans", []) if isinstance(payload, dict) else []
        return [dict(row) for row in rows if isinstance(row, dict)]

    def _save_pending_take_profits(self, plans: list[dict[str, Any]]) -> None:
        self._pending_tp_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._pending_tp_path.with_suffix(self._pending_tp_path.suffix + ".tmp")
        temporary.write_text(json.dumps({"plans": plans}, indent=2), encoding="utf-8")
        temporary.replace(self._pending_tp_path)

    def change_leverage(self, symbol: str, leverage: int) -> str | None:
        """Apply the configured leverage before opening a Bitunix order."""

        if not 1 <= int(leverage) <= 125:
            return "leverage_out_of_range"
        body = {
            "marginCoin": "USDT",
            "symbol": symbol.replace("/", "").replace("-", "").upper(),
            "leverage": int(leverage),
        }
        headers = self._sign_headers(body_json=json.dumps(body, separators=(",", ":")))
        try:
            payload = self._send(
                url=f"{self._base_url}{BITUNIX_CHANGE_LEVERAGE_PATH}",
                headers=headers,
                body=body,
            )
        except Exception as exc:  # noqa: BLE001
            return f"http_error: {exc}"
        if not isinstance(payload, dict) or payload.get("code") != 0:
            return str(payload.get("msg") if isinstance(payload, dict) else "invalid_response")
        return None

    def _build_body(self, order: OrderRequest) -> dict[str, Any]:
        if order.order_type not in {"MARKET", "LIMIT"}:
            raise ValueError(
                f"order_type_not_supported_by_bitunix_adapter: {order.order_type}"
            )
        if order.quantity <= 0:
            raise ValueError("quantity_must_be_positive")

        symbol = order.symbol.replace("/", "").upper()
        position_id = str(order.meta.get("position_id", "")).strip()
        if order.reduce_only and not position_id:
            raise ValueError("position_id_required_for_close")
        body: dict[str, Any] = {
            "symbol": symbol,
            "side": "BUY" if order.side == "BUY" else "SELL",
            "orderType": "MARKET" if order.order_type == "MARKET" else "LIMIT",
            "qty": _fmt_number(order.quantity),
            "reduceOnly": bool(order.reduce_only),
            # OPEN for entries, CLOSE for reduce-only (partial TP / exits).
            "tradeSide": "CLOSE" if order.reduce_only else "OPEN",
        }
        if position_id:
            body["positionId"] = position_id

        if order.order_type == "LIMIT":
            if order.price is None or order.price <= 0:
                raise ValueError("limit_price_required")
            body["price"] = _fmt_number(order.price)
            body["effect"] = "GTC"

        client_id = order.meta.get("client_order_id")
        if client_id:
            body["clientId"] = str(client_id)
        return body

    def _sign_headers(self, *, body_json: str) -> dict[str, str]:
        nonce = secrets.token_hex(16)
        timestamp = str(int(time.time() * 1000))
        digest_input = f"{nonce}{timestamp}{self._credentials.api_key}{body_json}"
        digest = hashlib.sha256(digest_input.encode("utf-8")).hexdigest()
        sign = hashlib.sha256(
            f"{digest}{self._credentials.api_secret}".encode("utf-8")
        ).hexdigest()
        return {
            "api-key": self._credentials.api_key,
            "sign": sign,
            "nonce": nonce,
            "timestamp": timestamp,
            "language": "en-US",
            "Content-Type": "application/json",
            "User-Agent": BITUNIX_USER_AGENT,
        }

    def _private_get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        canonical = "".join(f"{key}{params[key]}" for key in sorted(params))
        nonce = secrets.token_hex(16)
        timestamp = str(int(time.time() * 1000))
        digest = hashlib.sha256(
            f"{nonce}{timestamp}{self._credentials.api_key}{canonical}".encode("utf-8")
        ).hexdigest()
        sign = hashlib.sha256(
            f"{digest}{self._credentials.api_secret}".encode("utf-8")
        ).hexdigest()
        headers = {
            "api-key": self._credentials.api_key, "sign": sign,
            "nonce": nonce, "timestamp": timestamp, "language": "en-US",
            "Content-Type": "application/json", "User-Agent": BITUNIX_USER_AGENT,
        }
        url = f"{self._base_url}{path}?{urllib.parse.urlencode(params)}"
        if self._query_transport is not None:
            payload = self._query_transport(url=url, headers=headers, params=params)
        else:
            request = urllib.request.Request(url, headers=headers, method="GET")
            with urllib.request.urlopen(request, timeout=10) as response:
                raw = response.read().decode("utf-8")
                payload = json.loads(raw) if raw else {}
        if not isinstance(payload, dict) or payload.get("code") != 0:
            raise RuntimeError(str(payload.get("msg") if isinstance(payload, dict) else "invalid_response"))
        return payload

    def _post_success(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        headers = self._sign_headers(body_json=json.dumps(body, separators=(",", ":")))
        payload = self._send(url=f"{self._base_url}{path}", headers=headers, body=body)
        if not isinstance(payload, dict) or payload.get("code") != 0:
            raise RuntimeError(str(payload.get("msg") if isinstance(payload, dict) else "invalid_response"))
        return payload

    def _send(
        self, *, url: str, headers: dict[str, str], body: dict[str, Any],
    ) -> dict[str, Any]:
        if self._transport is not None:
            return self._transport(url=url, headers=headers, body=body)
        request = urllib.request.Request(
            url,
            data=json.dumps(body, separators=(",", ":")).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}

    def _to_execution_result(
        self, payload: dict[str, Any], order: OrderRequest, timestamp: str,
    ) -> ExecutionResult:
        code = payload.get("code")
        if code != 0:
            if code == 710002:
                _remember_openapi_unsupported(order.symbol)
            return ExecutionResult(
                status="REJECTED", order_id="", symbol=order.symbol,
                side=order.side, order_type=order.order_type,
                requested_quantity=order.quantity, filled_quantity=0.0,
                average_price=0.0, timestamp=timestamp,
                reason=str(payload.get("msg") or f"bitunix_error_code={code}"),
                meta={**order.meta, "raw": payload},
            )

        data = payload.get("data")
        if isinstance(data, list):
            data = next((item for item in data if isinstance(item, dict)), None)
        if not isinstance(data, dict):
            return ExecutionResult(
                status="REJECTED", order_id="", symbol=order.symbol,
                side=order.side, order_type=order.order_type,
                requested_quantity=order.quantity, filled_quantity=0.0,
                average_price=0.0, timestamp=timestamp,
                reason="empty_response_data",
                meta={**order.meta, "raw": payload},
            )
        order_id = str(data.get("orderId") or "")
        filled_qty = _float(data.get("dealVolume") or data.get("filledQty"))
        avg_price = _float(data.get("dealAvgPrice") or data.get("avgPrice"))

        if order.order_type == "MARKET" and filled_qty <= 0:
            status = "SUBMITTED"
        else:
            status = _map_status(
                status=str(data.get("status") or ""),
                filled=filled_qty,
                requested=order.quantity,
            )

        if order_id:
            try:
                self._record_order_metadata(order_id, order, timestamp, status=status)
            except OSError:
                # Metadata is observability only. An accepted exchange order
                # must never be reported as failed because local persistence
                # is temporarily unavailable.
                logger.warning(
                    "Could not persist Bitunix order metadata order_id=%s",
                    order_id,
                    exc_info=True,
                )

        return ExecutionResult(
            status=status, order_id=order_id, symbol=order.symbol,
            side=order.side, order_type=order.order_type,
            requested_quantity=order.quantity, filled_quantity=filled_qty,
            average_price=avg_price, timestamp=timestamp, reason="",
            meta={**order.meta, "raw": payload},
        )

    def _record_order_metadata(
        self, order_id: str, order: OrderRequest, timestamp: str,
        *, status: str | None = None,
    ) -> None:
        """Persist bot-owned reason/role for exact Bitunix order correlation."""

        if self._order_metadata_path is None:
            return
        try:
            payload = json.loads(self._order_metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        rows = payload.get("orders") if isinstance(payload, dict) else None
        if not isinstance(rows, dict):
            rows = {}
        role = str(order.meta.get("role") or "")
        reason = str(order.meta.get("reason") or role or "")
        rows[str(order_id)] = {
            "order_id": str(order_id),
            "symbol": _canonical_symbol(order.symbol),
            "role": role,
            "reason": reason,
            "status": status,
            "metadata_kind": order.meta.get("metadata_kind", "bot_order"),
            "trigger_price": order.meta.get("trigger_price"),
            "position_id": str(order.meta.get("position_id") or ""),
            "reduce_only": bool(order.reduce_only),
            "lifecycle_version": order.meta.get("lifecycle_version"),
            "strategy_version": order.meta.get("strategy_version"),
            "created_at": timestamp,
            "expires_in_seconds": order.meta.get("expires_in_seconds"),
            "expiry_candles": order.meta.get("expiry_candles"),
            "expiry_timeframe": order.meta.get("expiry_timeframe"),
            "entry_context": order.meta.get("entry_context"),
        }
        # Keep the registry bounded while preserving insertion order.
        rows = dict(list(rows.items())[-2000:])
        self._order_metadata_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._order_metadata_path.with_suffix(
            self._order_metadata_path.suffix + ".tmp"
        )
        temporary.write_text(json.dumps({"orders": rows}, indent=2), encoding="utf-8")
        temporary.replace(self._order_metadata_path)

    def _reject(
        self, order: OrderRequest, timestamp: str, reason: str,
    ) -> ExecutionResult:
        return ExecutionResult(
            status="REJECTED", order_id="", symbol=order.symbol,
            side=order.side, order_type=order.order_type,
            requested_quantity=order.quantity, filled_quantity=0.0,
            average_price=0.0, timestamp=timestamp, reason=reason,
            meta=order.meta,
        )

    def _load_minimum_amounts(self) -> dict[str, float]:
        try:
            payload = json.loads(self._min_amount_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return {
            str(symbol): _float(value)
            for symbol, value in payload.items()
            if _float(value) > 0
        }

    def _remember_minimum_amount(self, symbol: str, quantity: float) -> None:
        canonical = _canonical_symbol(symbol)
        if not canonical or quantity <= 0:
            return
        self._minimum_amounts[canonical] = max(
            quantity, self._minimum_amounts.get(canonical, 0.0),
        )
        try:
            self._min_amount_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._min_amount_path.with_suffix(
                self._min_amount_path.suffix + ".tmp"
            )
            temporary.write_text(
                json.dumps(self._minimum_amounts, indent=2), encoding="utf-8",
            )
            temporary.replace(self._min_amount_path)
        except OSError:
            logger.warning("Could not persist Bitunix minimum amount symbol=%s", canonical)


def _map_status(*, status: str, filled: float, requested: float) -> str:
    normalized = (status or "").upper()
    if normalized in {"FILLED", "COMPLETED"}:
        return "FILLED"
    if normalized in {"PART_FILLED", "PARTIALLY_FILLED", "PARTIAL"}:
        return "PARTIAL"
    if normalized in {"NEW", "SUBMITTED", "PENDING"}:
        return "SUBMITTED"
    if normalized in {"CANCELLED", "CANCELED", "EXPIRED"}:
        return "CANCELLED"
    if normalized in {"REJECTED", "FAILED"}:
        return "REJECTED"
    if filled >= requested and requested > 0:
        return "FILLED"
    if filled > 0:
        return "PARTIAL"
    return "SUBMITTED"


def _is_minimum_amount_rejection(result: ExecutionResult) -> bool:
    raw = result.meta.get("raw") if isinstance(result.meta, dict) else None
    code = raw.get("code") if isinstance(raw, dict) else None
    return code == 30017 or "minimum amount" in str(result.reason).lower()


def _fmt_number(value: float) -> str:
    return format(float(value), "f").rstrip("0").rstrip(".") or "0"


def _canonical_symbol(value: object) -> str:
    symbol = str(value or "").strip().upper().replace("-", "/")
    if "/" not in symbol and symbol.endswith("USDT") and len(symbol) > 4:
        symbol = f"{symbol[:-4]}/USDT"
    return symbol


def _canonical_position_side(value: object) -> str:
    side = str(value or "").strip().upper()
    if side in {"BUY", "LONG"}:
        return "LONG"
    if side in {"SELL", "SHORT"}:
        return "SHORT"
    return side


def _float(value: Any) -> float:
    try:
        return float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _remember_openapi_unsupported(symbol: str) -> None:
    """Persist pairs Bitunix explicitly rejects for OpenAPI trading."""

    normalized = str(symbol or "").strip().upper().replace("-", "/")
    if not normalized:
        return
    path = BITUNIX_OPENAPI_BLOCKLIST_PATH
    try:
        current = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, json.JSONDecodeError):
        current = {}
    symbols = current.get("symbols", []) if isinstance(current, dict) else []
    blocked = {str(value).strip().upper().replace("-", "/") for value in symbols}
    blocked.add(normalized)
    payload = {
        "symbols": sorted(blocked),
        "reason": "bitunix_openapi_error_710002",
        "updated_at_ms": int(time.time() * 1000),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temporary.replace(path)
    except OSError:
        # Failure to persist observability must not alter the exchange result.
        return
