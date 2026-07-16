"""Unit tests for ACR+ indicator primitives."""

from __future__ import annotations

from app.core.models import Candle
from app.indicators.acr import (
    ACRSwing,
    acr_swings,
    cisd_levels,
    detect_acr_pattern_at,
    equilibrium_range_from_swings,
    fair_value_gaps,
    has_displacement_fvg,
    latest_acr_pattern,
    latest_cisd,
    latest_opposing,
    latest_unfilled_fvg,
    mss_events,
    opposing_candles,
    previous_candle_equilibrium_continuation,
    previous_candle_equilibrium_reversal,
)


def _c(i: int, o: float, h: float, l: float, c: float, v: float = 1000.0) -> Candle:
    return Candle(
        symbol="TEST",
        timestamp=f"2026-07-15T00:{i:02d}:00Z",
        open=o, high=h, low=l, close=c, volume=v,
    )


def test_acr_swings_detects_middle_candle_extreme() -> None:
    candles = [
        _c(0, 100, 102, 99, 101),
        _c(1, 101, 110, 100, 108),
        _c(2, 108, 109, 104, 105),
        _c(3, 105, 106, 95, 98),
        _c(4, 98, 103, 97, 102),
    ]
    swings = acr_swings(candles)
    kinds = [(s.side, s.index, s.price) for s in swings]
    assert ("HIGH", 1, 110) in kinds
    assert ("LOW", 3, 95) in kinds


def test_acr_swings_ignores_edges_and_short_input() -> None:
    assert acr_swings([]) == []
    assert acr_swings([_c(0, 1, 2, 0.5, 1.5)]) == []


# FVG -----------------------------------------------------------------------


def test_fair_value_gaps_bullish_and_bearish() -> None:
    candles = [
        _c(0, 100, 102, 99, 101),
        _c(1, 101, 108, 100, 107),
        _c(2, 107, 110, 103, 109),
        _c(3, 109, 110, 104, 105),
        _c(4, 105, 106, 102, 103),
        _c(5, 103, 104, 98, 99),
        _c(6, 99, 100, 92, 93),
        _c(7, 93, 96, 88, 90),
    ]
    fvgs = fair_value_gaps(candles)
    triples = [(f.direction, round(f.bottom, 2), round(f.top, 2)) for f in fvgs]
    assert ("BULLISH", 102.0, 103.0) in triples
    assert ("BEARISH", 96.0, 98.0) in triples


def test_fvg_mitigated_and_filled_flags() -> None:
    candles = [
        _c(0, 100, 102, 99, 101),
        _c(1, 101, 108, 100, 107),
        _c(2, 107, 110, 103, 109),
        _c(3, 109, 110, 102.5, 104),
        _c(4, 104, 105, 101, 101.5),
    ]
    fvgs = [f for f in fair_value_gaps(candles) if f.direction == "BULLISH"]
    assert fvgs and fvgs[0].mitigated
    assert fvgs[0].filled


def test_latest_unfilled_fvg() -> None:
    candles = [
        _c(0, 100, 102, 99, 101),
        _c(1, 101, 108, 100, 107),
        _c(2, 107, 110, 103, 109),
        _c(3, 109, 111, 108, 110),
    ]
    fvgs = fair_value_gaps(candles)
    assert latest_unfilled_fvg(fvgs, "BULLISH") is not None
    assert latest_unfilled_fvg(fvgs, "BEARISH") is None


# CISD & MSS ----------------------------------------------------------------


def test_cisd_bearish_body_break() -> None:
    candles = [
        _c(0, 105, 106, 100, 101),
        _c(1, 101, 108, 100, 107),
        _c(2, 107, 108, 103, 104),
        _c(3, 104, 105, 100, 100.5),
    ]
    cisds = cisd_levels(candles)
    latest = latest_cisd(cisds, "BEARISH")
    assert latest is not None
    assert latest.price == 107


def test_cisd_bullish_body_break() -> None:
    candles = [
        _c(0, 100, 105, 100, 104),
        _c(1, 104, 105, 99, 100),
        _c(2, 100, 101, 96, 97),
        _c(3, 97, 105, 96, 103),
    ]
    cisds = cisd_levels(candles)
    latest = latest_cisd(cisds, "BULLISH")
    assert latest is not None
    assert latest.price == 100


def test_mss_wick_break() -> None:
    candles = [
        _c(0, 100, 102, 99, 101),
        _c(1, 101, 110, 100, 108),
        _c(2, 108, 109, 104, 105),
        _c(3, 105, 111, 104, 108),
    ]
    events = mss_events(candles)
    assert any(m.direction == "BULLISH" and m.swing_price == 110 for m in events)

    assert acr_swings([_c(0, 1, 2, 0.5, 1.5), _c(1, 1.5, 3, 1, 2)]) == []



# Opposing Candle -----------------------------------------------------------


def test_opposing_candle_bearish_series_creates_bullish_level() -> None:
    candles = [
        _c(0, 110, 111, 105, 106),
        _c(1, 106, 107, 100, 101),
        _c(2, 101, 102, 95, 96),
        _c(3, 96, 105, 95, 104),
    ]
    opps = opposing_candles(candles)
    bullish = [o for o in opps if o.direction == "BULLISH"]
    assert bullish and bullish[0].price == 110


def test_opposing_candle_bullish_series_creates_bearish_level() -> None:
    candles = [
        _c(0, 100, 105, 99, 104),
        _c(1, 104, 108, 103, 107),
        _c(2, 107, 110, 106, 109),
        _c(3, 109, 110, 100, 101),
    ]
    opps = opposing_candles(candles)
    bearish = [o for o in opps if o.direction == "BEARISH"]
    assert bearish and bearish[0].price == 100


def test_latest_opposing_respects_reference_index() -> None:
    candles = [
        _c(0, 100, 101, 99, 99.5),
        _c(1, 99.5, 100, 96, 97),
        _c(2, 97, 102, 96, 101),
        _c(3, 101, 105, 100, 104),
        _c(4, 104, 105, 98, 99),
    ]
    opps = opposing_candles(candles)
    op = latest_opposing(opps, "BULLISH", reference_index=3)
    assert op is not None
    assert op.price == 100



# ACR Pattern ---------------------------------------------------------------


def test_acr_pattern_bullish_expanded() -> None:
    candles = [
        _c(0, 105, 108, 103, 106),
        _c(1, 106, 108, 100, 105),
        _c(2, 105, 106, 98, 102),
        _c(3, 102, 108, 101, 107),
        _c(4, 107, 112, 106, 111),
    ]
    pattern = latest_acr_pattern(candles)
    assert pattern is not None
    assert pattern.direction == "BULLISH"
    assert pattern.stage == "expanded"
    assert pattern.candle2_wick_far == 98


def test_acr_pattern_bearish_confirmed() -> None:
    candles = [
        _c(0, 95, 97, 92, 94),
        _c(1, 94, 100, 93, 99),
        _c(2, 99, 105, 98, 100),
        _c(3, 100, 101, 95, 96),
    ]
    pattern = latest_acr_pattern(candles)
    assert pattern is not None
    assert pattern.direction == "BEARISH"
    assert pattern.stage in ("confirmed", "expanded")


def test_acr_pattern_invalid_when_c3_fails_equilibrium() -> None:
    candles = [
        _c(0, 105, 108, 103, 106),
        _c(1, 106, 108, 100, 105),
        _c(2, 105, 106, 98, 102),
        _c(3, 102, 103, 98.5, 99),
    ]
    pattern = detect_acr_pattern_at(candles, 2)
    assert pattern is not None
    assert pattern.stage == "invalid"


def test_acr_pattern_none_when_no_sweep() -> None:
    # Semua candle "inside bar" -> tidak ada sweep di kedua sisi.
    candles = [
        _c(0, 105, 110, 100, 107),
        _c(1, 106, 109, 101, 108),   # high < c0.high, low > c0.low
        _c(2, 107, 108.5, 102, 108),  # high < c1.high, low > c1.low
    ]
    assert detect_acr_pattern_at(candles, 1) is None
    assert detect_acr_pattern_at(candles, 2) is None


# Equilibrium & Displacement -----------------------------------------------


def test_equilibrium_range_from_swings() -> None:
    swing_low = ACRSwing(index=1, side="LOW", price=100.0, timestamp="t1")
    swing_high = ACRSwing(index=5, side="HIGH", price=120.0, timestamp="t5")
    eq = equilibrium_range_from_swings(swing_low, swing_high)
    assert eq.direction == "BULLISH"
    assert eq.equilibrium == 110
    assert eq.is_discount(105)
    assert eq.is_premium(115)


def test_previous_candle_equilibrium_helpers() -> None:
    candle = _c(0, 100, 110, 90, 95)
    assert previous_candle_equilibrium_continuation(candle) == 100
    rev = previous_candle_equilibrium_reversal(candle, "LOW")
    assert 90 <= rev <= 100


def test_has_displacement_fvg_forward() -> None:
    candles = [
        _c(0, 100, 102, 99, 101),
        _c(1, 101, 103, 100, 102),
        _c(2, 102, 110, 101, 109),
        _c(3, 109, 111, 108, 110),
        _c(4, 110, 111, 105, 106),
    ]
    fvg = has_displacement_fvg(candles, "BULLISH", after_index=1, lookforward=4)
    assert fvg is not None
    assert fvg.direction == "BULLISH"
