"""Order submission for the Binance USDⓈ-M Futures venue.

Design mirrors the existing spot ``BinanceOrderSubmissionEngine`` but with
futures-specific fields:

- ``positionSide`` — BOTH (one-way mode) or LONG/SHORT (hedge mode).
- ``reduceOnly`` — bool guard so risk-manager exits cannot flip the position.
- ``closePosition`` — special flag for STOP_MARKET / TAKE_PROFIT_MARKET.
- ``workingType`` / ``stopPrice`` — for conditional orders.

All submissions go through a :class:`FuturesLiveSafetyGate` first. The gate
follows the same three-toggle contract used for spot (``enabled``,
``dry_run``, ``confirm_live``). Callers must flip all three to submit real
orders.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.exchange.binance_futures.client import FuturesHttpClient, FuturesHttpError


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class PositionSide(str, Enum):
    BOTH = "BOTH"  # one-way mode
    LONG = "LONG"  # hedge mode long
    SHORT = "SHORT"  # hedge mode short


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_MARKET = "STOP_MARKET"
    TAKE_PROFIT = "TAKE_PROFIT"
    TAKE_PROFIT_MARKET = "TAKE_PROFIT_MARKET"
    TRAILING_STOP_MARKET = "TRAILING_STOP_MARKET"


class TimeInForce(str, Enum):
    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"
    GTX = "GTX"  # post-only


class WorkingType(str, Enum):
    MARK_PRICE = "MARK_PRICE"
    CONTRACT_PRICE = "CONTRACT_PRICE"



@dataclass(frozen=True)
class FuturesOrderRequest:
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float | None = None
    price: float | None = None
    position_side: PositionSide = PositionSide.BOTH
    time_in_force: TimeInForce | None = None
    stop_price: float | None = None
    working_type: WorkingType | None = None
    reduce_only: bool = False
    close_position: bool = False
    client_order_id: str | None = None
    activation_price: float | None = None  # trailing stop only
    callback_rate: float | None = None  # trailing stop only

    def to_params(self) -> dict[str, Any]:
        if not self.symbol:
            raise ValueError("symbol is required")
        if self.close_position and self.reduce_only:
            raise ValueError("close_position and reduce_only are mutually exclusive")
        if self.close_position and self.order_type not in {
            OrderType.STOP_MARKET,
            OrderType.TAKE_PROFIT_MARKET,
        }:
            raise ValueError(
                "close_position=True only valid for STOP_MARKET/TAKE_PROFIT_MARKET"
            )
        if not self.close_position and (self.quantity is None or self.quantity <= 0):
            raise ValueError("quantity must be positive unless close_position=True")
        if self.order_type is OrderType.LIMIT:
            if self.price is None or self.price <= 0:
                raise ValueError("LIMIT orders require a positive price")
            if self.time_in_force is None:
                raise ValueError("LIMIT orders require time_in_force")

        params: dict[str, Any] = {
            "symbol": self.symbol.upper(),
            "side": self.side.value,
            "type": self.order_type.value,
            "positionSide": self.position_side.value,
        }
        if self.quantity is not None:
            params["quantity"] = _fmt_float(self.quantity)
        if self.price is not None:
            params["price"] = _fmt_float(self.price)
        if self.stop_price is not None:
            params["stopPrice"] = _fmt_float(self.stop_price)
        if self.time_in_force is not None:
            params["timeInForce"] = self.time_in_force.value
        if self.working_type is not None:
            params["workingType"] = self.working_type.value
        if self.reduce_only:
            params["reduceOnly"] = True
        if self.close_position:
            params["closePosition"] = True
        if self.client_order_id:
            params["newClientOrderId"] = self.client_order_id
        if self.activation_price is not None:
            params["activationPrice"] = _fmt_float(self.activation_price)
        if self.callback_rate is not None:
            params["callbackRate"] = _fmt_float(self.callback_rate)
        return params


@dataclass(frozen=True)
class FuturesOrderResult:
    accepted: bool
    dry_run: bool
    order_id: int | None
    client_order_id: str | None
    status: str | None
    executed_qty: float
    avg_price: float
    reason: str | None = None
    raw_response: dict[str, Any] | None = None
    submitted_params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FuturesLiveSafetyGate:
    """Three-toggle gate: all must be True for real submission."""

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


class FuturesOrderSubmissionEngine:
    """Single entry point for ``POST /fapi/v1/order``.

    ``submit_order`` never bypasses the safety gate. When the gate blocks
    submission the request is short-circuited into a ``FuturesOrderResult``
    with ``accepted=False`` and a machine-readable ``reason`` so operators
    can trace exactly why an order was suppressed.
    """

    def __init__(
        self,
        client: FuturesHttpClient,
        safety_gate: FuturesLiveSafetyGate | None = None,
    ) -> None:
        self._client = client
        self._safety_gate = safety_gate or FuturesLiveSafetyGate()

    def submit_order(self, request: FuturesOrderRequest) -> FuturesOrderResult:
        try:
            params = request.to_params()
        except ValueError as exc:
            return FuturesOrderResult(
                accepted=False,
                dry_run=self._safety_gate.dry_run,
                order_id=None,
                client_order_id=request.client_order_id,
                status=None,
                executed_qty=0.0,
                avg_price=0.0,
                reason=f"validation_error: {exc}",
                submitted_params={},
            )

        block_reason = self._safety_gate.evaluate()
        if block_reason is not None:
            return FuturesOrderResult(
                accepted=False,
                dry_run=self._safety_gate.dry_run,
                order_id=None,
                client_order_id=request.client_order_id,
                status="DRY_RUN" if self._safety_gate.dry_run else None,
                executed_qty=0.0,
                avg_price=0.0,
                reason=block_reason,
                submitted_params=params,
            )

        try:
            response = self._client.post("/fapi/v1/order", params)
        except FuturesHttpError as exc:
            return FuturesOrderResult(
                accepted=False,
                dry_run=False,
                order_id=None,
                client_order_id=request.client_order_id,
                status=None,
                executed_qty=0.0,
                avg_price=0.0,
                reason=(
                    f"binance_error[{exc.code}]: {exc.message}"
                    if exc.code is not None
                    else exc.message
                ),
                submitted_params=params,
            )

        payload = response.body if isinstance(response.body, dict) else {}
        return FuturesOrderResult(
            accepted=True,
            dry_run=False,
            order_id=_coerce_int(payload.get("orderId")),
            client_order_id=str(payload.get("clientOrderId"))
            if payload.get("clientOrderId")
            else request.client_order_id,
            status=str(payload.get("status")) if payload.get("status") else None,
            executed_qty=_coerce_float(payload.get("executedQty")),
            avg_price=_coerce_float(payload.get("avgPrice")),
            raw_response=payload,
            submitted_params=params,
        )


def _fmt_float(value: float) -> str:
    return format(float(value), "f").rstrip("0").rstrip(".") or "0"


def _coerce_float(value: Any) -> float:
    try:
        return float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None

