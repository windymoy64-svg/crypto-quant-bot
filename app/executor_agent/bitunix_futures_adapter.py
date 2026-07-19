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
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from app.executor_agent.models import (
    ExecutionResult,
    OrderRequest,
    OrderType,
)


BITUNIX_FUTURES_BASE = "https://fapi.bitunix.com"
BITUNIX_USER_AGENT = "crypto-quant-bot/1.0 (+executor-agent)"
BITUNIX_PLACE_ORDER_PATH = "/api/v1/futures/trade/place_order"
BITUNIX_ACCOUNT_PATH = "/api/v1/futures/account"


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
    ) -> None:
        self._credentials = credentials
        self._safety_gate = safety_gate or BitunixLiveSafetyGate()
        self._base_url = base_url.rstrip("/")
        self._transport = transport  # optional callable(url, headers, body) -> dict

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

        stop = next((item for item in orders if item.meta.get("role") == "stop_loss"), None)
        take_profit = next(
            (item for item in orders if str(item.meta.get("role", "")).startswith("take_profit_")),
            None,
        )
        if stop is None or stop.stop_price is None or stop.stop_price <= 0:
            return [
                self._reject(item, timestamp, "protective_stop_required_before_live_entry")
                for item in orders
            ]
        if take_profit is None or take_profit.price is None or take_profit.price <= 0:
            return [
                self._reject(item, timestamp, "take_profit_required_before_live_entry")
                for item in orders
            ]

        try:
            body = self._build_body(entry)
            body.update({
                "slPrice": _fmt_number(stop.stop_price),
                "slStopType": "MARK",
                "slOrderType": "MARKET",
                "tpPrice": _fmt_number(take_profit.price),
                "tpStopType": "MARK",
                "tpOrderType": "MARKET",
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
        protective_results = [
            ExecutionResult(
                status="SUBMITTED" if entry_result.status != "REJECTED" else "REJECTED",
                order_id=entry_result.order_id,
                symbol=item.symbol, side=item.side, order_type=item.order_type,
                requested_quantity=item.quantity, filled_quantity=0.0,
                average_price=0.0, timestamp=timestamp,
                reason=("attached_to_entry" if entry_result.status != "REJECTED" else entry_result.reason),
                meta={**item.meta, "attached_to_entry": True},
            )
            for item in orders if item is not entry
        ]
        return [entry_result, *protective_results]

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
            return ExecutionResult(
                status="REJECTED", order_id="", symbol=order.symbol,
                side=order.side, order_type=order.order_type,
                requested_quantity=order.quantity, filled_quantity=0.0,
                average_price=0.0, timestamp=timestamp,
                reason=str(payload.get("msg") or f"bitunix_error_code={code}"),
                meta={**order.meta, "raw": payload},
            )

        data = payload.get("data") or {}
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

        return ExecutionResult(
            status=status, order_id=order_id, symbol=order.symbol,
            side=order.side, order_type=order.order_type,
            requested_quantity=order.quantity, filled_quantity=filled_qty,
            average_price=avg_price, timestamp=timestamp, reason="",
            meta={**order.meta, "raw": payload},
        )

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


def _fmt_number(value: float) -> str:
    return format(float(value), "f").rstrip("0").rstrip(".") or "0"


def _float(value: Any) -> float:
    try:
        return float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0
