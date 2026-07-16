"""Tests for ACR+ engine bridge helpers (position dict manipulation)."""

from __future__ import annotations

from app.core.models import Candle
from app.strategies.acr_engine_bridge import (
    apply_acr_breakeven,
    apply_acr_trailing,
    check_acr_invalidation,
)


def _c(i: int, o: float, h: float, l: float, c: float, v: float = 1000.0) -> Candle:
    return Candle(
        symbol="TEST",
        timestamp=f"2026-07-16T00:{i:02d}:00Z",
        open=o, high=h, low=l, close=c, volume=v,
    )


def _long_position(**overrides):
    base = {
        "symbol": "BTCUSDT",
        "side": "BUY",
        "entry": 100.0,
        "static_stop_loss": 95.0,
        "trailing_stop_loss": None,
        "trailing_active": False,
        "tp_hit": [False, False, False],
        "take_profit": [110.0, 120.0, 130.0],
    }
    base.update(overrides)
    return base


def _short_position(**overrides):
    base = {
        "symbol": "ETHUSDT",
        "side": "SELL",
        "entry": 100.0,
        "static_stop_loss": 105.0,
        "trailing_stop_loss": None,
        "trailing_active": False,
        "tp_hit": [False, False, False],
        "take_profit": [90.0, 80.0, 70.0],
    }
    base.update(overrides)
    return base


# apply_acr_breakeven -------------------------------------------------------


def test_breakeven_noop_before_tp1() -> None:
    pos = _long_position()
    assert apply_acr_breakeven(pos) is False
    assert pos["static_stop_loss"] == 95.0


def test_breakeven_long_moves_sl_to_entry_after_tp1() -> None:
    pos = _long_position(tp_hit=[True, False, False])
    assert apply_acr_breakeven(pos) is True
    assert pos["static_stop_loss"] == 100.0


def test_breakeven_short_moves_sl_to_entry_after_tp1() -> None:
    pos = _short_position(tp_hit=[True, False, False])
    assert apply_acr_breakeven(pos) is True
    assert pos["static_stop_loss"] == 100.0


def test_breakeven_does_not_lower_sl_below_current() -> None:
    # SL sudah di atas entry (long): tidak turun.
    pos = _long_position(tp_hit=[True, False, False], static_stop_loss=105.0)
    assert apply_acr_breakeven(pos) is False
    assert pos["static_stop_loss"] == 105.0


# apply_acr_trailing --------------------------------------------------------


def test_trailing_noop_before_tp1() -> None:
    pos = _long_position()
    ltf = [
        _c(0, 100, 102, 99, 101),
        _c(1, 101, 105, 100, 104),
        _c(2, 104, 106, 103, 105),
    ]
    assert apply_acr_trailing(pos, ltf) is False


def test_trailing_activates_after_tp1_with_swing_low() -> None:
    pos = _long_position(tp_hit=[True, False, False])
    # Buat swing LOW yg tegas di index 2 (low lebih rendah dari kiri & kanan).
    ltf = [
        _c(0, 100, 106, 104, 105),
        _c(1, 105, 108, 103, 107),
        _c(2, 107, 109, 100, 108),   # low 100 (paling rendah)
        _c(3, 108, 112, 105, 111),   # low 105 > 100 -> confirm swing low
        _c(4, 111, 115, 110, 114),
    ]
    changed = apply_acr_trailing(pos, ltf, buffer_pct=0.002)
    assert changed is True
    assert pos["trailing_active"] is True
    assert pos["trailing_stop_loss"] is not None
    assert pos["trailing_stop_loss"] < 114  # below current close


def test_trailing_short_activates_after_tp1_with_swing_high() -> None:
    pos = _short_position(tp_hit=[True, False, False])
    # Swing HIGH di index 2 (high paling tinggi diapit low neighbor).
    ltf = [
        _c(0, 100, 96, 94, 95),
        _c(1, 95, 92, 90, 91),
        _c(2, 91, 100, 89, 90),    # high 100 (paling tinggi)
        _c(3, 90, 95, 85, 87),     # high 95 < 100
        _c(4, 87, 90, 82, 83),
    ]
    changed = apply_acr_trailing(pos, ltf, buffer_pct=0.002)
    assert changed is True
    assert pos["trailing_active"] is True
    assert pos["trailing_stop_loss"] is not None
    assert pos["trailing_stop_loss"] > 83


# check_acr_invalidation ----------------------------------------------------


def test_invalidation_noop_before_tp1() -> None:
    pos = _long_position()
    ltf = [
        _c(0, 115, 116, 111, 112),
        _c(1, 112, 116, 111, 115),
        _c(2, 115, 116, 111, 112),  # would generate BEARISH CISD if tp1 hit
    ]
    assert check_acr_invalidation(pos, ltf) is None


def test_invalidation_detects_counter_cisd_after_tp1() -> None:
    pos = _long_position(tp_hit=[True, False, False])
    ltf = [
        _c(0, 115, 116, 111, 112),
        _c(1, 112, 116, 111, 115),
        _c(2, 115, 116, 111, 112),
    ]
    reason = check_acr_invalidation(pos, ltf)
    assert reason == "counter_cisd"


def test_invalidation_none_when_no_counter_signal() -> None:
    pos = _long_position(tp_hit=[True, False, False])
    ltf = [_c(i, 100 + i, 101 + i, 99 + i, 100.5 + i) for i in range(5)]
    reason = check_acr_invalidation(pos, ltf)
    assert reason is None
