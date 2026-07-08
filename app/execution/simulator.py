from __future__ import annotations

from dataclasses import dataclass
from itertools import count

from app.core.models import Candle
from app.events.events import OrderCreated, OrderFilled
from app.events.publisher import publish
from app.execution.fee import FeeModel
from app.execution.fill import FillResult, SimulatedFill
from app.execution.latency import LatencyModel
from app.execution.order import LiquidityType, OrderSide, OrderStatus, OrderType, SimulatedOrder
from app.execution.slippage import SlippageModel, SpreadModel


@dataclass(frozen=True)
class ExecutionSettings:
    maker_fee_rate: float = 0.0002
    taker_fee_rate: float = 0.001
    slippage_basis_points: float = 5.0
    spread_basis_points: float = 2.0
    latency_candles: int = 0
    max_fill_ratio: float = 1.0
    min_fill_ratio: float = 0.25
    liquidity: LiquidityType = LiquidityType.TAKER


class ExecutionSimulator:
    def __init__(self, settings: ExecutionSettings | None = None) -> None:
        self.settings = settings or ExecutionSettings()
        self.fees = FeeModel(self.settings.maker_fee_rate, self.settings.taker_fee_rate)
        self.spread = SpreadModel(self.settings.spread_basis_points)
        self.slippage = SlippageModel(self.settings.slippage_basis_points)
        self.latency = LatencyModel(self.settings.latency_candles)
        self._ids = count(1)

    def execute_market_order(
        self,
        *,
        symbol: str,
        side: OrderSide,
        quantity: float,
        requested_price: float,
        signal_index: int,
        candles: list[Candle],
    ) -> FillResult:
        order = SimulatedOrder(
            order_id=f"SIM-{next(self._ids):08d}",
            symbol=symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=max(quantity, 0.0),
            requested_price=requested_price,
            created_at=candles[signal_index].timestamp,
            liquidity=self.settings.liquidity,
        )
        order.add_event(order.created_at, OrderStatus.NEW, "order accepted by simulator")
        publish(
            OrderCreated(
                order_id=order.order_id,
                symbol=order.symbol,
                side=order.side.value,
                order_type=order.order_type.value,
                quantity=order.quantity,
                requested_price=order.requested_price,
                timestamp=order.created_at,
            )
        )

        if order.quantity <= 0 or requested_price <= 0:
            order.reject(order.created_at, "invalid quantity or price")
            return self._empty_result(order, "invalid quantity or price")

        execution_index = self.latency.execution_index(signal_index, len(candles) - 1)
        candle = candles[execution_index]
        price = self._execution_price(candle.close, side)
        fill_quantity = self._fill_quantity(order.quantity, candle.volume)

        if fill_quantity <= 0:
            order.cancel(candle.timestamp, "no simulated liquidity")
            return self._empty_result(order, "no simulated liquidity")

        order.apply_fill(fill_quantity, price, candle.timestamp)
        fill = self._build_fill(order, fill_quantity, price, candle.timestamp)
        publish(
            OrderFilled(
                order_id=order.order_id,
                symbol=order.symbol,
                side=order.side.value,
                quantity=round(fill_quantity, 8),
                price=round(price, 8),
                notional=round(fill.notional, 8),
                fee=round(fill.fee, 8),
                status=order.status.value,
                timestamp=candle.timestamp,
            )
        )
        return FillResult(
            order_id=order.order_id,
            status=order.status,
            fills=[fill],
            requested_quantity=round(order.quantity, 8),
            filled_quantity=round(order.filled_quantity, 8),
            average_price=round(order.average_fill_price, 8),
            total_notional=round(fill.notional, 8),
            total_fee=round(fill.fee, 8),
            liquidity=order.liquidity,
            reason=None if order.status == OrderStatus.FILLED else "partial_fill",
        )

    def _execution_price(self, mid_price: float, side: OrderSide) -> float:
        spread_price = self.spread.apply(mid_price, side)
        return self.slippage.apply(spread_price, side)

    def _fill_quantity(self, requested_quantity: float, candle_volume: float) -> float:
        available = max(candle_volume, 0.0) * max(self.settings.max_fill_ratio, 0.0)
        if available >= requested_quantity:
            return requested_quantity
        minimum = requested_quantity * max(min(self.settings.min_fill_ratio, 1.0), 0.0)
        return available if available >= minimum else 0.0

    def _build_fill(self, order: SimulatedOrder, quantity: float, price: float, timestamp: str) -> SimulatedFill:
        notional = quantity * price
        fee = self.fees.calculate(notional, order.liquidity)
        return SimulatedFill(
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side.value,
            quantity=round(quantity, 8),
            price=round(price, 8),
            notional=round(notional, 8),
            fee=round(fee, 8),
            liquidity=order.liquidity.value,
            timestamp=timestamp,
        )

    def _empty_result(self, order: SimulatedOrder, reason: str) -> FillResult:
        return FillResult(
            order_id=order.order_id,
            status=order.status,
            fills=[],
            requested_quantity=round(order.quantity, 8),
            filled_quantity=0.0,
            average_price=0.0,
            total_notional=0.0,
            total_fee=0.0,
            liquidity=order.liquidity,
            reason=reason,
        )