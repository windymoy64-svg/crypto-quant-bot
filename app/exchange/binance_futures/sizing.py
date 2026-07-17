"""Position sizing for USDⓈ-M Futures with liquidation-aware guards.

Given an entry price, stop-loss, and wallet balance the sizer returns:

- ``quantity`` — contract size to submit.
- ``notional`` — quantity * entry_price.
- ``initial_margin`` — notional / leverage.
- ``liquidation`` — :class:`LiquidationEstimate` derived from the bracket.

Two independent guards can veto the trade:

1. **Risk-per-trade**: loss between entry and stop must not exceed
   ``risk_per_trade_percent`` of wallet balance.
2. **Liquidation buffer**: the stop-loss must sit at least
   ``min_liquidation_buffer_percent`` closer to the entry than the
   liquidation price. This prevents the stop from being unreachable because
   the position gets liquidated first.

The sizer is intentionally pure (no I/O). Callers fetch the bracket table
elsewhere and pass it in, which keeps the math testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.exchange.binance_futures.brackets import SymbolBrackets
from app.exchange.binance_futures.risk_math import (
    LiquidationEstimate,
    PositionDirection,
    estimate_liquidation,
)


class SizingRejection(str, Enum):
    OK = "ok"
    INVALID_INPUT = "invalid_input"
    STOP_ON_WRONG_SIDE = "stop_on_wrong_side"
    RISK_PER_TRADE_ZERO_DISTANCE = "risk_per_trade_zero_distance"
    INSUFFICIENT_WALLET = "insufficient_wallet"
    STOP_BEYOND_LIQUIDATION = "stop_beyond_liquidation"
    LIQUIDATION_BUFFER_TOO_TIGHT = "liquidation_buffer_too_tight"


@dataclass(frozen=True)
class FuturesSizingResult:
    accepted: bool
    reason: SizingRejection
    direction: PositionDirection
    quantity: float
    notional: float
    initial_margin: float
    risk_amount: float
    liquidation: LiquidationEstimate | None
    detail: str | None = None


def _rejection(
    reason: SizingRejection,
    *,
    direction: PositionDirection,
    detail: str | None = None,
) -> FuturesSizingResult:
    return FuturesSizingResult(
        accepted=False,
        reason=reason,
        direction=direction,
        quantity=0.0,
        notional=0.0,
        initial_margin=0.0,
        risk_amount=0.0,
        liquidation=None,
        detail=detail,
    )


def size_position(
    *,
    direction: PositionDirection,
    entry_price: float,
    stop_price: float,
    wallet_balance: float,
    leverage: int,
    brackets: SymbolBrackets,
    risk_per_trade_percent: float,
    min_liquidation_buffer_percent: float = 25.0,
    quantity_step: float | None = None,
) -> FuturesSizingResult:
    """Compute the quantity for a futures entry.

    ``quantity_step`` (if provided) rounds the result down to the nearest
    multiple. Callers usually get this from the exchange ``LOT_SIZE`` filter.
    """

    if entry_price <= 0 or stop_price <= 0 or wallet_balance <= 0:
        return _rejection(
            SizingRejection.INVALID_INPUT,
            direction=direction,
            detail="entry_price, stop_price and wallet_balance must be positive",
        )
    if leverage <= 0:
        return _rejection(
            SizingRejection.INVALID_INPUT,
            direction=direction,
            detail="leverage must be positive",
        )
    if not 0.0 < risk_per_trade_percent <= 100.0:
        return _rejection(
            SizingRejection.INVALID_INPUT,
            direction=direction,
            detail="risk_per_trade_percent must be in (0, 100]",
        )

    if direction is PositionDirection.LONG and stop_price >= entry_price:
        return _rejection(
            SizingRejection.STOP_ON_WRONG_SIDE,
            direction=direction,
            detail=f"long entry={entry_price} needs stop_price < entry",
        )
    if direction is PositionDirection.SHORT and stop_price <= entry_price:
        return _rejection(
            SizingRejection.STOP_ON_WRONG_SIDE,
            direction=direction,
            detail=f"short entry={entry_price} needs stop_price > entry",
        )

    stop_distance = abs(entry_price - stop_price)
    if stop_distance <= 0:
        return _rejection(
            SizingRejection.RISK_PER_TRADE_ZERO_DISTANCE,
            direction=direction,
        )

    risk_amount = wallet_balance * (risk_per_trade_percent / 100.0)
    quantity = risk_amount / stop_distance
    if quantity_step and quantity_step > 0:
        quantity = _floor_to_step(quantity, quantity_step)
    if quantity <= 0:
        return _rejection(
            SizingRejection.INSUFFICIENT_WALLET,
            direction=direction,
            detail="wallet balance too small for one lot at this stop distance",
        )

    notional = entry_price * quantity
    initial_margin = notional / leverage
    if initial_margin > wallet_balance:
        return _rejection(
            SizingRejection.INSUFFICIENT_WALLET,
            direction=direction,
            detail=(
                f"initial_margin={initial_margin:.4f} exceeds wallet={wallet_balance:.4f}"
            ),
        )

    liquidation = estimate_liquidation(
        entry_price=entry_price,
        quantity=quantity,
        leverage=leverage,
        direction=direction,
        brackets=brackets,
    )

    # Stop must not sit past the liquidation price (would be moot).
    if direction is PositionDirection.LONG:
        if stop_price <= liquidation.liquidation_price:
            return _rejection(
                SizingRejection.STOP_BEYOND_LIQUIDATION,
                direction=direction,
                detail=(
                    f"long stop={stop_price} <= liquidation={liquidation.liquidation_price:.4f}"
                ),
            )
    else:
        if stop_price >= liquidation.liquidation_price:
            return _rejection(
                SizingRejection.STOP_BEYOND_LIQUIDATION,
                direction=direction,
                detail=(
                    f"short stop={stop_price} >= liquidation={liquidation.liquidation_price:.4f}"
                ),
            )

    # Liquidation must sit at least ``min_liquidation_buffer_percent`` further
    # from entry than the stop, so market noise doesn't wipe the position.
    liq_distance = abs(entry_price - liquidation.liquidation_price)
    buffer_ratio = liq_distance / stop_distance if stop_distance else 0.0
    required_ratio = 1.0 + (min_liquidation_buffer_percent / 100.0)
    if buffer_ratio < required_ratio:
        return _rejection(
            SizingRejection.LIQUIDATION_BUFFER_TOO_TIGHT,
            direction=direction,
            detail=(
                f"buffer_ratio={buffer_ratio:.3f} < required={required_ratio:.3f} "
                f"(liq_distance={liq_distance:.4f}, stop_distance={stop_distance:.4f})"
            ),
        )

    return FuturesSizingResult(
        accepted=True,
        reason=SizingRejection.OK,
        direction=direction,
        quantity=quantity,
        notional=notional,
        initial_margin=initial_margin,
        risk_amount=risk_amount,
        liquidation=liquidation,
    )


def _floor_to_step(value: float, step: float) -> float:
    """Round ``value`` down to the nearest multiple of ``step``.

    Uses integer division to avoid floating point drift when ``step`` is a
    decimal like 0.001.
    """

    if step <= 0:
        return value
    quotient = int(value / step)
    return quotient * step

