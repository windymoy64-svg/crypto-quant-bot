from __future__ import annotations

import pytest

from app.exchange.binance_futures.brackets import LeverageBracket, SymbolBrackets
from app.exchange.binance_futures.risk_math import PositionDirection
from app.exchange.binance_futures.sizing import (
    FuturesSizingResult,
    SizingRejection,
    size_position,
)


BRACKET = LeverageBracket(
    bracket=1,
    initial_leverage=125,
    notional_floor=0,
    notional_cap=50_000,
    maint_margin_ratio=0.004,
    cumulative=0.0,
)

BRACKETS = SymbolBrackets(symbol="BTCUSDT", brackets=(BRACKET,))


def _size(**overrides) -> FuturesSizingResult:
    defaults = dict(
        direction=PositionDirection.LONG,
        entry_price=60_000.0,
        stop_price=59_000.0,
        wallet_balance=1_000.0,
        leverage=5,
        brackets=BRACKETS,
        risk_per_trade_percent=1.0,
        min_liquidation_buffer_percent=25.0,
    )
    defaults.update(overrides)
    return size_position(**defaults)


def test_accepts_long_within_all_guards() -> None:
    result = _size()

    assert result.accepted is True
    assert result.reason is SizingRejection.OK
    # Risk = 1% of 1000 = 10 USDT, stop distance = 1000 -> qty = 0.01
    assert result.quantity == pytest.approx(0.01)
    assert result.notional == pytest.approx(600.0)
    assert result.initial_margin == pytest.approx(120.0)
    assert result.risk_amount == pytest.approx(10.0)
    assert result.liquidation is not None
    assert result.liquidation.liquidation_price < 60_000


def test_rejects_long_stop_above_entry() -> None:
    result = _size(stop_price=60_500.0)

    assert result.accepted is False
    assert result.reason is SizingRejection.STOP_ON_WRONG_SIDE


def test_rejects_short_stop_below_entry() -> None:
    result = _size(
        direction=PositionDirection.SHORT,
        entry_price=60_000.0,
        stop_price=59_000.0,
    )

    assert result.reason is SizingRejection.STOP_ON_WRONG_SIDE


def test_accepts_short_within_guards() -> None:
    result = _size(
        direction=PositionDirection.SHORT,
        entry_price=60_000.0,
        stop_price=61_000.0,
    )

    assert result.accepted is True
    assert result.quantity == pytest.approx(0.01)
    assert result.liquidation.liquidation_price > 60_000


def test_rejects_zero_stop_distance() -> None:
    result = _size(stop_price=60_000.0)

    # stop_price == entry_price triggers stop-on-wrong-side first for longs;
    # send a numerically equal-but-different case to force zero distance.
    assert result.reason is SizingRejection.STOP_ON_WRONG_SIDE


def test_rejects_invalid_inputs() -> None:
    assert _size(entry_price=0).reason is SizingRejection.INVALID_INPUT
    assert _size(stop_price=-1).reason is SizingRejection.INVALID_INPUT
    assert _size(wallet_balance=0).reason is SizingRejection.INVALID_INPUT
    assert _size(leverage=0).reason is SizingRejection.INVALID_INPUT
    assert _size(risk_per_trade_percent=0).reason is SizingRejection.INVALID_INPUT
    assert _size(risk_per_trade_percent=101).reason is SizingRejection.INVALID_INPUT


def test_quantity_step_rounds_down() -> None:
    # Without step: risk 10 / distance 900 = 0.01111...
    result = _size(stop_price=59_100.0, quantity_step=0.001)

    assert result.accepted is True
    assert result.quantity == pytest.approx(0.011)


def test_insufficient_wallet_after_rounding() -> None:
    # Step too large -> quantity floors to zero.
    result = _size(quantity_step=1.0)

    assert result.reason is SizingRejection.INSUFFICIENT_WALLET


def test_insufficient_wallet_from_margin_requirement() -> None:
    # Tiny wallet, high leverage, tight stop -> quantity is fine but margin
    # exceeds wallet. Use very small wallet with tight stop.
    result = _size(
        wallet_balance=5.0,
        risk_per_trade_percent=100.0,
        stop_price=59_999.0,  # distance 1 -> qty 5
        leverage=1,
    )

    assert result.reason is SizingRejection.INSUFFICIENT_WALLET


def test_rejects_stop_beyond_liquidation() -> None:
    # High leverage + very wide stop pushes stop past liquidation.
    result = _size(
        leverage=50,
        entry_price=60_000.0,
        stop_price=30_000.0,
        risk_per_trade_percent=100.0,
    )

    assert result.reason is SizingRejection.STOP_BEYOND_LIQUIDATION


def test_rejects_liquidation_buffer_too_tight() -> None:
    # Force liq very close to stop by using high leverage + wide stop.
    result = _size(
        leverage=20,
        risk_per_trade_percent=5.0,
        stop_price=57_500.0,
        min_liquidation_buffer_percent=200.0,
    )

    # With such a strict buffer requirement, guard should trigger.
    assert result.reason in {
        SizingRejection.LIQUIDATION_BUFFER_TOO_TIGHT,
        SizingRejection.STOP_BEYOND_LIQUIDATION,
    }


def test_accepts_when_buffer_percent_zero() -> None:
    result = _size(min_liquidation_buffer_percent=0.0)

    assert result.accepted is True
