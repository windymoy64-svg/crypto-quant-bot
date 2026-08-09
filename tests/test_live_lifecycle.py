from __future__ import annotations

from dataclasses import replace

from app.core.models import Candle
from app.execution.lifecycle_contract import execute_exit_gate
from app.execution.live_lifecycle import (
    LiveLifecycleController, LiveLifecycleState, LiveLifecycleStore,
    apply_live_lifecycle_monitor,
)
from app.executor_agent.models import ExecutionResult


class StatefulAdapter:
    def __init__(self) -> None:
        self.rows = [
            {"id": "tp1", "positionId": "p1", "symbol": "BTCUSDT", "tpPrice": "106", "tpQty": "0.3"},
            {"id": "tp2", "positionId": "p1", "symbol": "BTCUSDT", "tpPrice": "109", "tpQty": "0.3"},
            {"id": "tp3", "positionId": "p1", "symbol": "BTCUSDT", "tpPrice": "112", "tpQty": "0.4"},
            {"id": "sl1", "positionId": "p1", "symbol": "BTCUSDT", "slPrice": "97", "slQty": "1"},
        ]
        self.cancelled: list[str] = []
        self.placed: list[tuple[str, float]] = []
        self.tightened: list[float] = []

    def pending_tpsl(self, *, symbol=None, position_id=None):
        return [row.copy() for row in self.rows if not position_id or row["positionId"] == position_id]

    def cancel_tpsl_order(self, *, symbol, order_id):
        self.cancelled.append(order_id)
        self.rows = [row for row in self.rows if row["id"] != order_id]
        return True

    def place_lifecycle_take_profit(self, *, symbol, position_id, side, role, price, quantity):
        self.placed.append((role, quantity))
        self.rows.append({
            "id": f"new-{role}", "positionId": position_id,
            "symbol": symbol.replace("/", ""), "tpPrice": str(price),
            "tpQty": str(quantity),
        })
        return ExecutionResult(
            status="SUBMITTED", order_id=f"new-{role}", symbol=symbol,
            side=side, order_type="LIMIT", requested_quantity=quantity,
            filled_quantity=0, average_price=0, timestamp="now",
        )

    def tighten_stop(self, *, symbol, position_id, side, new_stop, quantity):
        self.tightened.append(new_stop)
        for row in self.rows:
            if row.get("slPrice"):
                row["slPrice"] = str(new_stop)
                row["slQty"] = str(quantity)
        return {}


def _state() -> LiveLifecycleState:
    return LiveLifecycleState(
        position_id="p1", symbol="BTC/USDT", side="LONG",
        entry_price=100, initial_stop=97, current_stop=97,
        initial_quantity=1, remaining_quantity=1,
        tp_levels=[106, 109, 112],
    )


def _candles() -> list[Candle]:
    values = [(100, 103, 99, 102), (102, 106, 101, 105),
              (105, 108, 100, 107), (107, 112, 105, 111),
              (111, 115, 110, 114)]
    return [Candle("BTC/USDT", f"2026-01-01T00:0{i}:00Z", o, h, l, c, 1)
            for i, (o, h, l, c) in enumerate(values)]


def test_legacy_position_is_never_adopted_or_mutated(tmp_path) -> None:
    adapter = StatefulAdapter()
    controller = LiveLifecycleController(adapter, LiveLifecycleStore(tmp_path / "state.json"))
    assert controller.reconcile({"position_id": "legacy", "quantity": 1}) is None
    assert adapter.cancelled == []


def test_hold_restart_resume_restores_remaining_ladder_idempotently(tmp_path) -> None:
    adapter = StatefulAdapter()
    store = LiveLifecycleStore(tmp_path / "state.json")
    controller = LiveLifecycleController(adapter, store)
    controller.register(_state())
    controller.reconcile({"position_id": "p1", "quantity": 1})
    held = controller.set_hold("p1", True)
    assert held.hold_mode is True
    assert set(adapter.cancelled) == {"tp1", "tp2", "tp3"}
    restarted = LiveLifecycleController(adapter, LiveLifecycleStore(tmp_path / "state.json"))
    restarted.set_hold("p1", True)
    assert len(adapter.cancelled) == 3
    restarted.set_hold("p1", False)
    assert [role for role, _ in adapter.placed] == [
        "take_profit_1", "take_profit_2", "take_profit_3",
    ]
    assert sum(qty for _, qty in adapter.placed) == 1


def test_resume_after_partial_allocates_only_remaining_quantity(tmp_path) -> None:
    adapter = StatefulAdapter()
    store = LiveLifecycleStore(tmp_path / "state.json")
    state = replace(_state(), hold_mode=True, remaining_quantity=0.7,
                    tp_hit=[True, False, False], tp_order_ids={})
    controller = LiveLifecycleController(adapter, store)
    controller.register(state)
    controller.set_hold("p1", False)
    assert [role for role, _ in adapter.placed] == ["take_profit_2", "take_profit_3"]
    assert sum(qty for _, qty in adapter.placed) == 0.7


def test_rearm_after_partial_restores_missing_remaining_tps(tmp_path) -> None:
    adapter = StatefulAdapter()
    adapter.rows = [adapter.rows[-1]]
    store = LiveLifecycleStore(tmp_path / "state.json")
    controller = LiveLifecycleController(adapter, store)
    controller.register(replace(_state(), remaining_quantity=0.7))

    roles = controller.rearm_remaining_take_profits({
        "position_id": "p1", "quantity": 0.7,
    })

    assert roles == ["take_profit_2", "take_profit_3"]
    assert [role for role, _ in adapter.placed] == roles
    assert [qty for _, qty in adapter.placed] == [0.3, 0.4]


def test_shared_acr_trailing_tightens_live_stop_and_persists(tmp_path) -> None:
    adapter = StatefulAdapter()
    store = LiveLifecycleStore(tmp_path / "state.json")
    controller = LiveLifecycleController(adapter, store)
    controller.register(replace(_state(), hold_mode=True))
    new_stop = controller.update_stop_from_candles("p1", _candles())
    assert new_stop is not None and new_stop >= 100
    assert adapter.tightened == [new_stop]
    assert store.load()["p1"].current_stop == new_stop


def test_monitor_hold_manages_registered_but_skips_legacy(tmp_path) -> None:
    adapter = StatefulAdapter()
    controller = LiveLifecycleController(
        adapter, LiveLifecycleStore(tmp_path / "state.json"),
    )
    legacy = apply_live_lifecycle_monitor(
        controller, position={"position_id": "legacy", "quantity": 1},
        decision={"action": "HOLD", "meta": {"hold_mode": True}},
        ltf_candles=_candles(),
    )
    assert legacy["managed"] is False
    controller.register(_state())
    managed = apply_live_lifecycle_monitor(
        controller, position={"position_id": "p1", "quantity": 1},
        decision={"action": "HOLD", "meta": {"hold_mode": True}},
        ltf_candles=_candles(),
    )
    assert managed["managed"] is True
    assert managed["hold_mode"] is True


def test_execute_exit_gate_allows_immediate_exit_without_pnl_filter(tmp_path) -> None:
    """IMMEDIATE urgency bypasses PnL bands."""
    position = {"opened_at": "2026-01-01T10:00:00+00:00"}
    assert execute_exit_gate(
        position=position, decision_action="EXIT", urgency="IMMEDIATE", pnl_ratio=0.5
    ) is True


def test_execute_exit_gate_next_candle_skips_fresh_position() -> None:
    """NEXT_CANDLE respects min_hold_seconds for fresh positions."""
    from datetime import datetime, UTC, timedelta
    
    # Create a timestamp just 120 seconds ago (under 300s min hold)
    opened_at = datetime.now(tz=UTC) - timedelta(seconds=120)
    opened_at_str = opened_at.isoformat().replace("+00:00", "") + "+00:00"
    
    position = {"opened_at": opened_at_str}
    result = execute_exit_gate(
        position=position, decision_action="EXIT", urgency="NEXT_CANDLE", pnl_ratio=-0.4
    )
    # Should be blocked because position is less than 5 minutes old
    assert result is False


def test_execute_exit_gate_next_candle_skips_small_pnl_range(tmp_path) -> None:
    """NEXT_CANDLE blocks exits when -0.3R < pnl_ratio <= 1.0R."""
    position = {"opened_at": "2026-01-01T09:50:00+00:00"}  # old enough (>300s)
    assert execute_exit_gate(
        position=position, decision_action="EXIT", urgency="NEXT_CANDLE", pnl_ratio=-0.2
    ) is False
    assert execute_exit_gate(
        position=position, decision_action="EXIT", urgency="NEXT_CANDLE", pnl_ratio=0.5
    ) is False
    assert execute_exit_gate(
        position=position, decision_action="EXIT", urgency="NEXT_CANDLE", pnl_ratio=1.0
    ) is False


def test_execute_exit_gate_next_candle_allows_big_winner_or_loss(tmp_path) -> None:
    """NEXT_CANDLE allows exits when pnl_ratio <= -0.3R or > 1.0R."""
    position = {"opened_at": "2026-01-01T09:50:00+00:00"}  # old enough
    assert execute_exit_gate(
        position=position, decision_action="EXIT", urgency="NEXT_CANDLE", pnl_ratio=-0.4
    ) is True
    assert execute_exit_gate(
        position=position, decision_action="EXIT", urgency="NEXT_CANDLE", pnl_ratio=1.5
    ) is True


def test_execute_exit_gate_non_exit_decision_always_true(tmp_path) -> None:
    """Non-EXIT actions are always allowed."""
    position = {"opened_at": "2026-01-01T10:00:00+00:00"}
    assert execute_exit_gate(
        position=position, decision_action="HOLD", urgency="NEXT_CANDLE", pnl_ratio=-0.5
    ) is True
    assert execute_exit_gate(
        position=position, decision_action="ENTRY_BUY", urgency="NEXT_CANDLE", pnl_ratio=-0.5
    ) is True
