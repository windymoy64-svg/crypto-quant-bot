from __future__ import annotations

import pytest

from app.exchange.binance_futures.brackets import LeverageBracket, SymbolBrackets
from app.exchange.binance_futures.risk_math import (
    PositionDirection,
    estimate_liquidation,
    initial_margin,
    liquidation_price,
    maintenance_margin,
)


BRACKET_LOW = LeverageBracket(
    bracket=1,
    initial_leverage=125,
    notional_floor=0,
    notional_cap=50_000,
    maint_margin_ratio=0.004,
    cumulative=0.0,
)

BRACKET_MID = LeverageBracket(
    bracket=2,
    initial_leverage=100,
    notional_floor=50_000,
    notional_cap=250_000,
    maint_margin_ratio=0.005,
    cumulative=50.0,
)

BRACKETS = SymbolBrackets(symbol="BTCUSDT", brackets=(BRACKET_LOW, BRACKET_MID))


def test_initial_margin_divides_notional_by_leverage() -> None:
    assert initial_margin(6000, 10) == pytest.approx(600.0)
    assert initial_margin(0, 5) == 0.0


def test_initial_margin_validates_inputs() -> None:
    with pytest.raises(ValueError):
        initial_margin(1000, 0)
    with pytest.raises(ValueError):
        initial_margin(-100, 5)


def test_maintenance_margin_uses_bracket_mmr_and_cum() -> None:
    # 60000 notional in the MID bracket -> 60000 * 0.005 - 50 = 250
    assert maintenance_margin(60_000, BRACKET_MID) == pytest.approx(250.0)


def test_maintenance_margin_clamps_to_zero() -> None:
    tiny = LeverageBracket(
        bracket=99,
        initial_leverage=1,
        notional_floor=0,
        notional_cap=1,
        maint_margin_ratio=0.001,
        cumulative=1_000_000.0,
    )
    assert maintenance_margin(100, tiny) == 0.0


def test_long_liquidation_matches_binance_formula() -> None:
    liq = liquidation_price(
        entry_price=60_000,
        quantity=0.1,
        wallet_balance=600.0,
        direction=PositionDirection.LONG,
        bracket=BRACKET_LOW,
    )
    # (600 + 0 - 0.1*60000) / (0.1 * (0.004 - 1)) ~= 54216.87
    assert liq == pytest.approx(54216.87, rel=1e-4)


def test_short_liquidation_matches_binance_formula() -> None:
    liq = liquidation_price(
        entry_price=60_000,
        quantity=0.1,
        wallet_balance=600.0,
        direction=PositionDirection.SHORT,
        bracket=BRACKET_LOW,
    )
    # (600 + 0 + 6000) / (0.1 * 1.004) ~= 65737.05
    assert liq == pytest.approx(65737.05, rel=1e-4)


def test_liquidation_rejects_non_positive_quantity_or_price() -> None:
    with pytest.raises(ValueError):
        liquidation_price(
            entry_price=60_000,
            quantity=0,
            wallet_balance=100,
            direction=PositionDirection.LONG,
            bracket=BRACKET_LOW,
        )
    with pytest.raises(ValueError):
        liquidation_price(
            entry_price=0,
            quantity=0.1,
            wallet_balance=100,
            direction=PositionDirection.LONG,
            bracket=BRACKET_LOW,
        )


def test_estimate_liquidation_returns_full_breakdown() -> None:
    estimate = estimate_liquidation(
        entry_price=60_000,
        quantity=0.1,
        leverage=10,
        direction=PositionDirection.LONG,
        brackets=BRACKETS,
    )

    assert estimate.bracket.bracket == 1  # notional=6000 falls in low tier
    assert estimate.initial_margin == pytest.approx(600.0)
    assert estimate.maintenance_margin == pytest.approx(6000 * 0.004)
    assert estimate.liquidation_price == pytest.approx(54216.87, rel=1e-4)
    assert estimate.distance_percent > 0
    assert estimate.distance_percent < 100


def test_estimate_liquidation_selects_higher_tier() -> None:
    # Notional 100000 -> falls in BRACKET_MID (50000..250000)
    estimate = estimate_liquidation(
        entry_price=100_000,
        quantity=1,
        leverage=20,
        direction=PositionDirection.LONG,
        brackets=BRACKETS,
    )

    assert estimate.bracket.bracket == 2
    assert estimate.bracket.maint_margin_ratio == pytest.approx(0.005)


def test_estimate_liquidation_extra_wallet_pushes_liq_further() -> None:
    baseline = estimate_liquidation(
        entry_price=60_000,
        quantity=0.1,
        leverage=10,
        direction=PositionDirection.LONG,
        brackets=BRACKETS,
    )
    padded = estimate_liquidation(
        entry_price=60_000,
        quantity=0.1,
        leverage=10,
        direction=PositionDirection.LONG,
        brackets=BRACKETS,
        extra_wallet=500.0,
    )

    # More wallet -> lower liq price for a long position (safer).
    assert padded.liquidation_price < baseline.liquidation_price
    assert padded.distance_percent > baseline.distance_percent


def test_estimate_liquidation_short_symmetry() -> None:
    long_est = estimate_liquidation(
        entry_price=60_000,
        quantity=0.1,
        leverage=10,
        direction=PositionDirection.LONG,
        brackets=BRACKETS,
    )
    short_est = estimate_liquidation(
        entry_price=60_000,
        quantity=0.1,
        leverage=10,
        direction=PositionDirection.SHORT,
        brackets=BRACKETS,
    )

    assert short_est.liquidation_price > 60_000
    assert long_est.liquidation_price < 60_000
    # Distances should be within a small tolerance of each other.
    assert abs(short_est.distance_percent - long_est.distance_percent) < 0.5
