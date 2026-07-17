"""Pure-Python risk math for USDⓈ-M Futures positions.

Isolated from any I/O so the equations can be unit-tested in isolation.

The liquidation formula is the standard Binance USDⓈ-M formula (isolated
margin, one-way position mode). For a long position:

    liq = (entry_price * qty - wallet_balance - cum) /
          (qty * (mmr - 1))

For a short position (same formula but the signs flip on qty):

    liq = (entry_price * qty + wallet_balance + cum) /
          (qty * (mmr + 1))

where ``cum`` is the cumulative maintenance amount from the leverage bracket
and ``wallet_balance`` is the isolated margin (or portion of cross wallet
allocated to the position).

Reference: https://www.binance.com/en/support/faq/how-to-calculate-liquidation-price-of-usd%E2%93%A2-m-futures-contracts-b3c689c1f50a44cabb3a84e663b81d93
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.exchange.binance_futures.brackets import LeverageBracket, SymbolBrackets


class PositionDirection(str, Enum):
    LONG = "long"
    SHORT = "short"


@dataclass(frozen=True)
class LiquidationEstimate:
    liquidation_price: float
    bracket: LeverageBracket
    initial_margin: float
    maintenance_margin: float
    distance_percent: float  # (entry - liq) / entry * 100 for long, mirrored for short


def initial_margin(notional: float, leverage: int) -> float:
    """Initial margin = notional / leverage."""

    if leverage <= 0:
        raise ValueError("leverage must be positive")
    if notional < 0:
        raise ValueError("notional must be non-negative")
    return notional / leverage


def maintenance_margin(notional: float, bracket: LeverageBracket) -> float:
    """Maintenance margin = notional * MMR - cumulative offset.

    Clamped to zero so tiny notionals don't produce negative requirements.
    """

    return max(0.0, notional * bracket.maint_margin_ratio - bracket.cumulative)


def liquidation_price(
    *,
    entry_price: float,
    quantity: float,
    wallet_balance: float,
    direction: PositionDirection,
    bracket: LeverageBracket,
) -> float:
    """Return the estimated liquidation price for an isolated position.

    ``wallet_balance`` should be the isolated margin actually allocated to
    the position (for cross positions callers pass the full wallet balance).
    """

    if quantity <= 0:
        raise ValueError("quantity must be positive")
    if entry_price <= 0:
        raise ValueError("entry_price must be positive")

    mmr = bracket.maint_margin_ratio
    cum = bracket.cumulative

    if direction is PositionDirection.LONG:
        numerator = wallet_balance + cum - quantity * entry_price
        denominator = quantity * (mmr - 1.0)
    else:
        numerator = wallet_balance + cum + quantity * entry_price
        denominator = quantity * (mmr + 1.0)

    if denominator == 0:
        raise ValueError("degenerate liquidation formula (denominator=0)")
    return max(0.0, numerator / denominator)


def estimate_liquidation(
    *,
    entry_price: float,
    quantity: float,
    leverage: int,
    direction: PositionDirection,
    brackets: SymbolBrackets,
    extra_wallet: float = 0.0,
) -> LiquidationEstimate:
    """Compute liquidation price + margin figures in one call.

    ``extra_wallet`` lets callers reflect additional isolated margin they
    plan to add on top of the base initial margin.
    """

    notional = entry_price * quantity
    bracket = brackets.bracket_for(notional)
    im = initial_margin(notional, leverage)
    mm = maintenance_margin(notional, bracket)
    wallet = im + extra_wallet

    liq = liquidation_price(
        entry_price=entry_price,
        quantity=quantity,
        wallet_balance=wallet,
        direction=direction,
        bracket=bracket,
    )
    if direction is PositionDirection.LONG:
        distance = (entry_price - liq) / entry_price * 100.0
    else:
        distance = (liq - entry_price) / entry_price * 100.0

    return LiquidationEstimate(
        liquidation_price=liq,
        bracket=bracket,
        initial_margin=im,
        maintenance_margin=mm,
        distance_percent=distance,
    )
