"""Binance USDⓈ-M Futures adapter for the Executor Agent.

Translates Executor Agent ``OrderRequest`` objects into Binance Futures
``FuturesOrderRequest`` payloads and submits them via the existing
``FuturesOrderSubmissionEngine`` (which enforces the three-toggle safety
gate). Never bypasses that gate.
"""

from __future__ import annotations

from typing import Any

from app.exchange.binance_futures.orders import (
    FuturesOrderRequest,
    FuturesOrderResult,
    FuturesOrderSubmissionEngine,
    OrderSide as FuturesOrderSide,
    OrderType as FuturesOrderType,
    PositionSide,
    TimeInForce,
    WorkingType,
)
from app.executor_agent.models import (
    ExecutionResult,
    OrderRequest,
    OrderType,
)


class BinanceFuturesExecutorAdapter:
    """Adapter between Executor Agent and Binance Futures submission engine.

    The adapter is stateless. All safety checks (enabled + dry_run + confirm)
    live inside ``FuturesOrderSubmissionEngine``.
    """

    def __init__(
        self,
        submission_engine: FuturesOrderSubmissionEngine,
        *,
        position_side: PositionSide = PositionSide.BOTH,
        default_time_in_force: TimeInForce = TimeInForce.GTC,
        working_type: WorkingType | None = None,
    ) -> None:
        self._engine = submission_engine
        self._position_side = position_side
        self._default_time_in_force = default_time_in_force
        self._working_type = working_type

    def place_order(
        self,
        order: OrderRequest,
        *,
        timestamp: str,
    ) -> ExecutionResult:
        """Submit a single Executor OrderRequest to Binance Futures."""
        try:
            futures_request = self._to_futures_request(order)
        except ValueError as exc:
            return ExecutionResult(
                status="REJECTED",
                order_id="",
                symbol=order.symbol,
                side=order.side,
                order_type=order.order_type,
                requested_quantity=order.quantity,
                filled_quantity=0.0,
                average_price=0.0,
                timestamp=timestamp,
                reason=f"invalid_request: {exc}",
                meta=order.meta,
            )

        result = self._engine.submit_order(futures_request)
        return self._to_execution_result(result, order, timestamp)

    def _to_futures_request(self, order: OrderRequest) -> FuturesOrderRequest:
        side = FuturesOrderSide.BUY if order.side == "BUY" else FuturesOrderSide.SELL
        order_type = self._translate_order_type(order.order_type)
        time_in_force = (
            self._default_time_in_force
            if order_type is FuturesOrderType.LIMIT
            else None
        )
        working_type = self._working_type if order.stop_price is not None else None

        return FuturesOrderRequest(
            symbol=order.symbol.replace("/", ""),
            side=side,
            order_type=order_type,
            quantity=order.quantity if order.quantity > 0 else None,
            price=order.price if order_type is FuturesOrderType.LIMIT else None,
            position_side=self._position_side,
            time_in_force=time_in_force,
            stop_price=order.stop_price,
            working_type=working_type,
            reduce_only=order.reduce_only,
        )

    @staticmethod
    def _translate_order_type(order_type: OrderType) -> FuturesOrderType:
        mapping = {
            "MARKET": FuturesOrderType.MARKET,
            "LIMIT": FuturesOrderType.LIMIT,
            "STOP_MARKET": FuturesOrderType.STOP_MARKET,
            "STOP_LIMIT": FuturesOrderType.STOP,
        }
        try:
            return mapping[order_type]
        except KeyError as exc:  # pragma: no cover - guarded by Literal
            raise ValueError(f"unsupported_order_type: {order_type}") from exc

    def _to_execution_result(
        self,
        futures_result: FuturesOrderResult,
        order: OrderRequest,
        timestamp: str,
    ) -> ExecutionResult:
        if not futures_result.accepted:
            return ExecutionResult(
                status="REJECTED",
                order_id=str(futures_result.order_id or ""),
                symbol=order.symbol,
                side=order.side,
                order_type=order.order_type,
                requested_quantity=order.quantity,
                filled_quantity=0.0,
                average_price=0.0,
                timestamp=timestamp,
                reason=str(futures_result.reason or ""),
                meta={**order.meta, "raw": futures_result.raw_response},
            )

        status = _map_binance_status(
            futures_result.status or "",
            requested_quantity=order.quantity,
            filled_quantity=futures_result.executed_qty,
        )
        return ExecutionResult(
            status=status,
            order_id=str(futures_result.order_id or ""),
            symbol=order.symbol,
            side=order.side,
            order_type=order.order_type,
            requested_quantity=order.quantity,
            filled_quantity=float(futures_result.executed_qty or 0.0),
            average_price=float(futures_result.avg_price or 0.0),
            timestamp=timestamp,
            reason=str(futures_result.reason or ""),
            meta={
                **order.meta,
                "client_order_id": futures_result.client_order_id,
                "raw": futures_result.raw_response,
            },
        )


def _map_binance_status(
    status: str, *, requested_quantity: float, filled_quantity: float,
) -> str:
    normalized = (status or "").upper()
    if normalized == "FILLED":
        return "FILLED"
    if normalized == "PARTIALLY_FILLED":
        return "PARTIAL"
    if normalized in {"NEW", "ACCEPTED"}:
        return "SUBMITTED"
    if normalized in {"CANCELED", "CANCELLED", "EXPIRED"}:
        return "CANCELLED"
    if normalized == "REJECTED":
        return "REJECTED"
    if filled_quantity <= 0 and requested_quantity > 0:
        return "SUBMITTED"
    if 0 < filled_quantity < requested_quantity:
        return "PARTIAL"
    return "FILLED"
