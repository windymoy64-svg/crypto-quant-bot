from __future__ import annotations

from app.core.models import Candle
from app.indicators.liquidity_structure import (
    LiquidityPool,
    SweepEvent,
    SwingPoint,
    Zone,
    liquidity_pools,
    sr_zones,
    structure_state,
    sweep_events,
    swing_points,
)


def _c(
    index: int,
    open_: float,
    high: float,
    low: float,
    close: float,
    volume: float = 1000.0,
) -> Candle:
    return Candle(
        symbol="TEST",
        timestamp=f"2026-07-06T00:{index:02d}:00Z",
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


# ---------------------------------------------------------------------------
# swing_points
# ---------------------------------------------------------------------------


def test_swing_points_detects_symmetric_fractal_highs_and_lows() -> None:
    # Fractal high at index 2 (110), fractal low at index 5 (90), fractal
    # high at index 8 (115), fractal low at index 11 (85).
    candles = [
        _c(0, 100, 102, 99, 101),
        _c(1, 101, 105, 100, 104),
        _c(2, 104, 110, 103, 108),   # swing high
        _c(3, 108, 109, 104, 105),
        _c(4, 105, 106, 95, 96),
        _c(5, 96, 97, 90, 92),        # swing low
        _c(6, 92, 100, 91, 99),
        _c(7, 99, 108, 98, 107),
        _c(8, 107, 115, 106, 112),   # swing high (higher -> HH)
        _c(9, 112, 113, 105, 106),
        _c(10, 106, 107, 88, 90),
        _c(11, 90, 91, 85, 87),       # swing low (lower -> LL)
        _c(12, 87, 95, 86, 94),
        _c(13, 94, 96, 90, 95),
    ]

    swings = swing_points(candles, left=2, right=2)

    indices = [s.index for s in swings]
    assert indices == [2, 5, 8, 11]

    kinds = {s.index: s.kind for s in swings}
    assert kinds[2] == "HH"   # first high: seeded HH
    assert kinds[5] == "HL"   # first low: seeded HL
    assert kinds[8] == "HH"   # 115 > 110
    assert kinds[11] == "LL"  # 85 < 90

    sides = {s.index: s.side for s in swings}
    assert sides[2] == "HIGH"
    assert sides[5] == "LOW"


def test_swing_points_is_deterministic() -> None:
    candles = [
        _c(i, 100 + i, 105 + i, 95 + i, 100 + i)
        if i not in {3, 7}
        else _c(i, 100 + i, 120, 95 + i, 100 + i)
        for i in range(15)
    ]

    first = swing_points(candles, 2, 2)
    second = swing_points(candles, 2, 2)

    assert [s.to_dict() for s in first] == [s.to_dict() for s in second]


def test_swing_points_returns_empty_for_short_series() -> None:
    candles = [_c(i, 100, 101, 99, 100) for i in range(4)]
    assert swing_points(candles, 2, 2) == []


def test_swing_points_rejects_invalid_window() -> None:
    candles = [_c(i, 100, 101, 99, 100) for i in range(10)]
    raised = False
    try:
        swing_points(candles, 0, 2)
    except ValueError:
        raised = True
    assert raised, "expected ValueError for left=0"


# ---------------------------------------------------------------------------
# structure_state
# ---------------------------------------------------------------------------


def _uptrend_swings() -> list[SwingPoint]:
    # Alternating highs then lows building HH + HL.
    return [
        SwingPoint(2, "t2", 110.0, "HH", "HIGH"),
        SwingPoint(5, "t5", 90.0, "HL", "LOW"),   # first low seeded HL
        SwingPoint(8, "t8", 120.0, "HH", "HIGH"),
        SwingPoint(11, "t11", 95.0, "HL", "LOW"),
    ]


def _downtrend_swings() -> list[SwingPoint]:
    return [
        SwingPoint(2, "t2", 110.0, "HH", "HIGH"),  # first high seeded HH
        SwingPoint(5, "t5", 90.0, "HL", "LOW"),
        SwingPoint(8, "t8", 105.0, "LH", "HIGH"),
        SwingPoint(11, "t11", 80.0, "LL", "LOW"),
    ]


def test_structure_state_detects_uptrend_with_bos() -> None:
    state = structure_state(_uptrend_swings())

    assert state.trend == "UP"
    assert state.last_bos is not None and state.last_bos.index == 8
    # No LH exists yet in uptrend so no CHoCH signal.
    assert state.last_choch is None


def test_structure_state_detects_downtrend_with_bos_and_choch() -> None:
    state = structure_state(_downtrend_swings())

    assert state.trend == "DOWN"
    assert state.last_bos is not None and state.last_bos.index == 11
    # HH seeded at index 2 counts as CHoCH-against-current-trend signal.
    assert state.last_choch is not None and state.last_choch.index == 2


def test_structure_state_returns_side_for_mixed_swings() -> None:
    mixed = [
        SwingPoint(2, "t2", 110.0, "HH", "HIGH"),
        SwingPoint(5, "t5", 90.0, "HL", "LOW"),
        SwingPoint(8, "t8", 120.0, "HH", "HIGH"),
        SwingPoint(11, "t11", 80.0, "LL", "LOW"),
    ]
    state = structure_state(mixed)

    assert state.trend == "SIDE"
    assert state.last_bos is None
    assert state.last_choch is None


def test_structure_state_empty_swings() -> None:
    state = structure_state([])
    assert state.trend == "SIDE"
    assert state.last_bos is None
    assert state.last_choch is None


# ---------------------------------------------------------------------------
# sr_zones
# ---------------------------------------------------------------------------


def test_sr_zones_builds_support_and_resistance_from_swings() -> None:
    # Swing high at 2 (high=110, close=108 -> zone [108, 110]).
    # Swing low at 5 (low=90, close=92 -> zone [90, 92]).
    candles = [
        _c(0, 100, 102, 99, 101),
        _c(1, 101, 105, 100, 104),
        _c(2, 104, 110, 103, 108),
        _c(3, 108, 109, 104, 105),
        _c(4, 105, 106, 95, 96),
        _c(5, 96, 97, 90, 92),
        _c(6, 92, 100, 91, 99),
        _c(7, 99, 103, 98, 102),
        _c(8, 102, 104, 100, 103),
        _c(9, 103, 105, 101, 104),
    ]
    swings = swing_points(candles, 2, 2)
    zones = sr_zones(candles, swings)

    kinds = sorted(z.kind for z in zones)
    assert kinds == ["RESISTANCE", "SUPPORT"]

    resistance = next(z for z in zones if z.kind == "RESISTANCE")
    support = next(z for z in zones if z.kind == "SUPPORT")

    assert resistance.price_high == 110.0
    assert resistance.price_low == 108.0  # max(open=104, close=108)
    assert support.price_low == 90.0
    assert support.price_high == 92.0     # min(open=96, close=92)
    assert resistance.touches == 1
    assert support.touches == 1
    assert resistance.mitigated is False
    assert support.mitigated is False


def test_sr_zones_marks_support_mitigated_when_later_close_below() -> None:
    # Swing low at index 3 (low=90, close=92 -> zone [90, 92]).
    # Later candles bounce, then a strong bear candle at index 8 closes at 85
    # (below zone.price_low=90) while its low 84 stays above no other swing
    # low, and index 9 recovers so index 8 is not the deepest fractal low.
    candles = [
        _c(0, 100, 102, 99, 101),
        _c(1, 101, 103, 100, 102),
        _c(2, 102, 104, 101, 103),
        _c(3, 103, 104, 90, 92),      # swing low: zone [90, 92]
        _c(4, 92, 100, 91, 99),
        _c(5, 99, 103, 98, 102),
        _c(6, 102, 104, 100, 103),
        _c(7, 103, 104, 100, 101),
        _c(8, 101, 102, 84, 85),      # close 85 < 90 -> mitigates support
        _c(9, 85, 96, 83, 95),        # rebounds; low 83 keeps index 8 non-fractal
        _c(10, 95, 100, 94, 99),
        _c(11, 99, 102, 97, 101),
    ]
    swings = swing_points(candles, 2, 2)
    zones = sr_zones(candles, swings)

    support = next((z for z in zones if z.kind == "SUPPORT" and 90 in (z.price_low,)), None)
    # The swing low at index 3 with price 90 must produce a zone anchored at 90.
    matching = [z for z in zones if z.kind == "SUPPORT" and z.price_low == 90.0]
    assert matching, f"expected support zone anchored at 90, got {zones}"
    assert matching[0].mitigated is True


# ---------------------------------------------------------------------------
# liquidity_pools
# ---------------------------------------------------------------------------


def test_liquidity_pools_marks_swept_and_fresh_correctly() -> None:
    # Swing high at index 2 (110). A later candle wicks up to 111 -> swept.
    # Swing low at index 5 (90). No later candle wicks below 90 -> fresh.
    candles = [
        _c(0, 100, 102, 99, 101),
        _c(1, 101, 105, 100, 104),
        _c(2, 104, 110, 103, 108),   # swing high
        _c(3, 108, 109, 104, 105),
        _c(4, 105, 106, 95, 96),
        _c(5, 96, 97, 90, 92),        # swing low
        _c(6, 92, 100, 91, 99),
        _c(7, 99, 108, 98, 105),
        _c(8, 105, 111, 104, 106),   # wick sweeps buy-side pool at 110
        _c(9, 106, 107, 100, 101),
        _c(10, 101, 103, 99, 100),
        _c(11, 100, 101, 98, 99),
    ]
    swings = swing_points(candles, 2, 2)
    pools = liquidity_pools(candles, swings)

    buy_pools = [p for p in pools if p.side == "BUY_SIDE"]
    sell_pools = [p for p in pools if p.side == "SELL_SIDE"]

    assert any(p.price == 110.0 and p.swept and not p.fresh for p in buy_pools)
    assert any(p.price == 90.0 and not p.swept and p.fresh for p in sell_pools)


def test_liquidity_pools_all_fresh_when_no_later_penetration() -> None:
    candles = [
        _c(0, 100, 102, 99, 101),
        _c(1, 101, 108, 100, 107),
        _c(2, 107, 115, 106, 113),   # swing high 115
        _c(3, 113, 114, 108, 109),
        _c(4, 109, 110, 100, 101),
        _c(5, 101, 102, 90, 91),      # swing low 90
        _c(6, 91, 95, 90.5, 94),
        _c(7, 94, 100, 93, 99),
        _c(8, 99, 105, 98, 104),
    ]
    swings = swing_points(candles, 2, 2)
    pools = liquidity_pools(candles, swings)

    buy_pool = next(p for p in pools if p.side == "BUY_SIDE" and p.price == 115.0)
    assert buy_pool.fresh is True and buy_pool.swept is False



# ---------------------------------------------------------------------------
# sweep_events
# ---------------------------------------------------------------------------


def test_sweep_events_confirmed_when_close_returns_to_origin_side() -> None:
    # Candle 8 wicks to 111 (above swing high 110) then closes at 106
    # (below 110) -> confirmed sweep (liquidity grab).
    candles = [
        _c(0, 100, 102, 99, 101),
        _c(1, 101, 105, 100, 104),
        _c(2, 104, 110, 103, 108),
        _c(3, 108, 109, 104, 105),
        _c(4, 105, 106, 95, 96),
        _c(5, 96, 97, 90, 92),
        _c(6, 92, 100, 91, 99),
        _c(7, 99, 108, 98, 105),
        _c(8, 105, 111, 104, 106),   # sweep candle
        _c(9, 106, 107, 100, 101),
        _c(10, 101, 103, 99, 100),
        _c(11, 100, 101, 98, 99),
    ]
    swings = swing_points(candles, 2, 2)
    pools = liquidity_pools(candles, swings)
    events = sweep_events(candles, pools)

    buy_side_events = [e for e in events if e.pool_side == "BUY_SIDE"]
    assert len(buy_side_events) == 1
    event = buy_side_events[0]
    assert event.pool_price == 110.0
    assert event.sweep_index == 8
    assert event.wick_price == 111.0
    assert event.close_price == 106.0
    assert event.confirmed is True


def test_sweep_events_not_confirmed_on_genuine_breakout() -> None:
    # Later candle breaks and closes at 115 (above swing high 110)
    # -> breakout, not liquidity grab -> confirmed=False.
    candles = [
        _c(0, 100, 102, 99, 101),
        _c(1, 101, 105, 100, 104),
        _c(2, 104, 110, 103, 108),   # swing high
        _c(3, 108, 109, 104, 105),
        _c(4, 105, 106, 95, 96),
        _c(5, 96, 100, 95, 99),
        _c(6, 99, 108, 98, 107),
        _c(7, 107, 112, 106, 111),
        _c(8, 111, 116, 110, 115),   # breakout: close 115 > 110
        _c(9, 115, 118, 114, 117),
        _c(10, 117, 120, 116, 119),
    ]
    swings = swing_points(candles, 2, 2)
    pools = liquidity_pools(candles, swings)
    events = sweep_events(candles, pools)

    matching = [
        e for e in events if e.pool_side == "BUY_SIDE" and e.pool_price == 110.0
    ]
    assert matching, f"expected sweep event for 110, got {events}"
    assert matching[0].confirmed is False


def test_sweep_events_skips_fresh_pools() -> None:
    candles = [
        _c(0, 100, 102, 99, 101),
        _c(1, 101, 108, 100, 107),
        _c(2, 107, 115, 106, 113),
        _c(3, 113, 114, 108, 109),
        _c(4, 109, 110, 100, 101),
        _c(5, 101, 102, 90, 91),
        _c(6, 91, 95, 90.5, 94),
        _c(7, 94, 100, 93, 99),
        _c(8, 99, 105, 98, 104),
    ]
    swings = swing_points(candles, 2, 2)
    pools = liquidity_pools(candles, swings)
    events = sweep_events(candles, pools)

    fresh_pools = [p for p in pools if p.fresh]
    assert len(fresh_pools) == len(pools)
    assert events == []



# ---------------------------------------------------------------------------
# JSON serializability + backward compatibility
# ---------------------------------------------------------------------------


def test_all_dataclasses_are_json_serializable() -> None:
    import json

    candles = [
        _c(0, 100, 102, 99, 101),
        _c(1, 101, 105, 100, 104),
        _c(2, 104, 110, 103, 108),
        _c(3, 108, 109, 104, 105),
        _c(4, 105, 106, 95, 96),
        _c(5, 96, 97, 90, 92),
        _c(6, 92, 100, 91, 99),
        _c(7, 99, 108, 98, 105),
        _c(8, 105, 111, 104, 106),
        _c(9, 106, 107, 100, 101),
    ]
    swings = swing_points(candles, 2, 2)
    state = structure_state(swings)
    zones = sr_zones(candles, swings)
    pools = liquidity_pools(candles, swings)
    events = sweep_events(candles, pools)

    payload = {
        "swings": [s.to_dict() for s in swings],
        "state": state.to_dict(),
        "zones": [z.to_dict() for z in zones],
        "pools": [p.to_dict() for p in pools],
        "events": [e.to_dict() for e in events],
    }
    encoded = json.dumps(payload)
    assert isinstance(encoded, str)
    assert "swings" in encoded


def test_existing_structure_module_still_importable() -> None:
    # Legacy scalar helpers in app/indicators/structure.py must keep working
    # unchanged. New module must not shadow or alter them. The legacy
    # ``find_swing_low`` only looks at strict internal minima within the
    # lookback window, so use a fixture with a clear V shape.
    from app.indicators.structure import find_swing_high, find_swing_low

    candles = [
        _c(0, 100, 102, 99, 101),
        _c(1, 101, 105, 100, 104),
        _c(2, 104, 110, 103, 108),   # internal swing high
        _c(3, 108, 109, 100, 101),
        _c(4, 101, 102, 95, 96),      # internal swing low
        _c(5, 96, 100, 94, 99),
        _c(6, 99, 104, 98, 103),
    ]
    assert find_swing_high(candles, lookback=7) == 110.0
    # Legacy helper walks backwards and returns the most recent internal
    # swing low, which is candle 5 (low=94) here.
    assert find_swing_low(candles, lookback=7) == 94.0


def test_module_types_are_exposed() -> None:
    # The dataclasses must be importable directly for downstream sprints.
    assert SwingPoint.__name__ == "SwingPoint"
    assert Zone.__name__ == "Zone"
    assert LiquidityPool.__name__ == "LiquidityPool"
    assert SweepEvent.__name__ == "SweepEvent"

