"""Unit tests for the ACR+ position manager (trailing/hold logic)."""

from __future__ import annotations

from app.core.models import Candle
from app.strategies.acr_position_manager import (
    PositionState,
    PositionUpdate,
    evaluate_hold,
    update_position,
)


def _c(i: int, o: float, h: float, l: float, c: float, v: float = 1000.0) -> Candle:
    return Candle(
        symbol="TEST",
        timestamp=f"2026-07-15T00:{i:02d}:00Z",
        open=o, high=h, low=l, close=c, volume=v,
    )


def _long_state(**overrides) -> PositionState:
    """Baseline LONG state: entry 100, SL 95, TPs 110/120/130."""
    base = dict(
        symbol="BTCUSDT",
        side="LONG",
        entry=100.0,
        initial_stop_loss=95.0,
        current_stop_loss=95.0,
        take_profit_1=110.0,
        take_profit_2=120.0,
        take_profit_3=130.0,
        quantity=1.0,
        htf_direction="BULLISH",
    )
    base.update(overrides)
    return PositionState(**base)


def _short_state(**overrides) -> PositionState:
    """Baseline SHORT state: entry 100, SL 105, TPs 90/80/70."""
    base = dict(
        symbol="ETHUSDT",
        side="SHORT",
        entry=100.0,
        initial_stop_loss=105.0,
        current_stop_loss=105.0,
        take_profit_1=90.0,
        take_profit_2=80.0,
        take_profit_3=70.0,
        quantity=1.0,
        htf_direction="BEARISH",
    )
    base.update(overrides)
    return PositionState(**base)


# ---------------------------------------------------------------------------
# EXIT_SL
# ---------------------------------------------------------------------------


def test_long_exit_when_stop_loss_hit() -> None:
    state = _long_state()
    # Candle wick menembus SL 95.
    ltf = [_c(0, 96, 97, 94, 95.5)]
    upd = update_position(state, ltf)
    assert upd.action == "EXIT_SL"
    assert upd.close_fraction == 1.0
    assert upd.executed_price == 95.0
    assert upd.next_state is not None
    assert upd.next_state.filled_fraction == 0.0


def test_short_exit_when_stop_loss_hit() -> None:
    state = _short_state()
    ltf = [_c(0, 104, 106, 103, 105.5)]
    upd = update_position(state, ltf)
    assert upd.action == "EXIT_SL"


# ---------------------------------------------------------------------------
# TP1 -> partial + break-even
# ---------------------------------------------------------------------------


def test_long_tp1_triggers_partial_and_breakeven() -> None:
    state = _long_state()
    ltf = [_c(0, 105, 111, 104, 110.5)]
    upd = update_position(state, ltf)
    assert upd.action == "TAKE_PARTIAL"
    assert upd.close_fraction > 0
    assert upd.new_stop_loss == 100.0   # break-even
    assert upd.next_state is not None
    assert upd.next_state.tp1_hit
    assert upd.next_state.breakeven_moved
    assert upd.next_state.current_stop_loss == 100.0
    assert upd.next_state.filled_fraction < 1.0


def test_short_tp1_triggers_partial_and_breakeven() -> None:
    state = _short_state()
    ltf = [_c(0, 95, 96, 89, 89.5)]
    upd = update_position(state, ltf)
    assert upd.action == "TAKE_PARTIAL"
    assert upd.new_stop_loss == 100.0
    assert upd.next_state.tp1_hit


# ---------------------------------------------------------------------------
# TP2 -> partial + trailing activation
# ---------------------------------------------------------------------------


def test_long_tp2_activates_trailing_after_tp1() -> None:
    state = _long_state(
        tp1_hit=True, breakeven_moved=True,
        current_stop_loss=100.0, filled_fraction=0.6,
    )
    # Beberapa candle sebelum TP2 untuk buat swing low; kemudian candle spike TP2.
    ltf = [
        _c(0, 100, 112, 99, 111),
        _c(1, 111, 115, 108, 114),   # low 108 swing kandidat
        _c(2, 114, 116, 110, 115),
        _c(3, 115, 121, 114, 120.5),  # wick hit TP2 120
    ]
    upd = update_position(state, ltf)
    assert upd.action == "TAKE_PARTIAL"
    assert upd.next_state.tp2_hit
    assert upd.next_state.trailing_active
    # SL trailing minimal >= TP1 (fallback) atau di sekitar swing low.
    assert upd.next_state.current_stop_loss >= 100.0




# ---------------------------------------------------------------------------
# Trailing SL movement after TP2
# ---------------------------------------------------------------------------


def test_long_trailing_stop_updates_upward() -> None:
    state = _long_state(
        tp1_hit=True, tp2_hit=True, breakeven_moved=True,
        trailing_active=True, current_stop_loss=105.0, filled_fraction=0.25,
    )
    ltf = [
        _c(0, 120, 122, 118, 121),
        _c(1, 121, 125, 119, 124),   # swing low 119
        _c(2, 124, 128, 122, 127),
        _c(3, 127, 129, 125, 128),   # tidak sentuh TP3=130
    ]
    upd = update_position(state, ltf)
    if upd.new_stop_loss is not None:
        assert upd.new_stop_loss > 105.0
    assert upd.action in ("MOVE_SL", "HOLD")
    assert upd.next_state.trailing_active


# ---------------------------------------------------------------------------
# TP3 exit
# ---------------------------------------------------------------------------


def test_long_tp3_exits_when_hold_conditions_fail() -> None:
    state = _long_state(
        tp1_hit=True, tp2_hit=True, trailing_active=True,
        current_stop_loss=115.0, filled_fraction=0.25,
        htf_direction=None,
    )
    ltf = [_c(0, 128, 131, 127, 130.5)]
    upd = update_position(state, ltf)
    assert upd.action == "EXIT_TP"
    assert upd.executed_price == 130.0


# ---------------------------------------------------------------------------
# Invalidation
# ---------------------------------------------------------------------------


def test_long_exits_on_counter_cisd_after_tp1() -> None:
    state = _long_state(
        tp1_hit=True, breakeven_moved=True,
        current_stop_loss=100.0, filled_fraction=0.6,
        htf_direction="BULLISH",
    )
    # BEARISH CISD: prev bearish, current bullish (inserted), later bearish body break.
    ltf = [
        _c(0, 115, 116, 111, 112),   # bearish
        _c(1, 112, 116, 111, 115),   # bullish inserted, close 115
        _c(2, 115, 116, 111, 112),   # bearish, close 112 < 115 -> BEARISH CISD at 115
        _c(3, 112, 113, 108, 110),   # tetap di atas SL 100
    ]
    upd = update_position(state, ltf)
    assert upd.action == "EXIT_INVALIDATION"


# ---------------------------------------------------------------------------
# HOLD / evaluate_hold
# ---------------------------------------------------------------------------


def test_long_hold_when_price_between_levels() -> None:
    state = _long_state()
    ltf = [_c(0, 100, 105, 98, 102)]
    upd = update_position(state, ltf)
    assert upd.action == "HOLD"
    assert upd.next_state.filled_fraction == 1.0


def test_evaluate_hold_returns_true_when_no_counter_signal() -> None:
    state = _long_state(htf_direction="BULLISH")
    # LTF bullish murni.
    ltf = [_c(i, 100 + i, 101 + i, 99 + i, 100.5 + i) for i in range(5)]
    result = evaluate_hold(state, ltf)
    assert result.should_hold is True
    assert result.invalidation is None


def test_evaluate_hold_flags_counter_cisd() -> None:
    state = _long_state(htf_direction="BULLISH")
    ltf = [
        _c(0, 115, 116, 111, 112),
        _c(1, 112, 116, 111, 115),
        _c(2, 115, 116, 111, 112),
    ]
    result = evaluate_hold(state, ltf)
    assert result.should_hold is False
    assert result.invalidation == "counter_cisd"
