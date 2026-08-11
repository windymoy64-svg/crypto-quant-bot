from __future__ import annotations

from dataclasses import replace

import pytest

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
    controller = LiveLifecycleController(adapter, store, trailing_stop_percent=3)
    controller.register(replace(_state(), hold_mode=True))
    new_stop = controller.update_stop_from_candles("p1", _candles())
    assert new_stop is not None and 100 < new_stop < 114
    assert adapter.tightened == [new_stop]
    assert store.load()["p1"].current_stop == new_stop


def test_percentage_trailing_waits_for_long_activation_threshold(tmp_path) -> None:
    adapter = StatefulAdapter()
    store = LiveLifecycleStore(tmp_path / "state.json")
    controller = LiveLifecycleController(adapter, store, trailing_stop_percent=3)
    controller.register(_state())

    candles = [Candle("BTC/USDT", "2026-01-01T00:00:00Z", 100, 102, 99, 102, 1)]

    assert controller.update_stop_from_candles("p1", candles) is None
    assert adapter.tightened == []
    assert store.load()["p1"].trailing_active is False


def test_percentage_trailing_activates_on_high_even_if_candle_closes_below_threshold(tmp_path) -> None:
    adapter = StatefulAdapter()
    store = LiveLifecycleStore(tmp_path / "state.json")
    controller = LiveLifecycleController(adapter, store, trailing_stop_percent=3)
    controller.register(_state())
    candles = [Candle("BTC/USDT", "2026-01-01T00:00:00Z", 100, 104, 99, 102, 1)]

    new_stop = controller.update_stop_from_candles("p1", candles)

    assert new_stop is not None
    assert new_stop > 100
    assert store.load()["p1"].trailing_active is True


def test_existing_position_can_register_without_tp_ladder(tmp_path) -> None:
    adapter = StatefulAdapter()
    adapter.rows = [adapter.rows[-1]]
    controller = LiveLifecycleController(
        adapter, LiveLifecycleStore(tmp_path / "state.json"), trailing_stop_percent=3,
    )

    assert controller.register_existing_position({
        "position_id": "p1", "symbol": "BTC/USDT", "side": "LONG",
        "entry_price": 100, "stop_loss": 97, "quantity": 1,
    }) is True


def test_short_trailing_activates_on_low_even_if_candle_closes_above_threshold(tmp_path) -> None:
    adapter = StatefulAdapter()
    store = LiveLifecycleStore(tmp_path / "state.json")
    controller = LiveLifecycleController(adapter, store, trailing_stop_percent=3)
    controller.register(replace(_state(), side="SHORT", initial_stop=103, current_stop=103))
    candles = [Candle("BTC/USDT", "2026-01-01T00:00:00Z", 100, 101, 96, 99, 1)]

    new_stop = controller.update_stop_from_candles("p1", candles)

    assert new_stop is not None
    assert new_stop < 100


def test_percentage_trailing_short_stays_below_entry_and_only_improves(tmp_path) -> None:
    adapter = StatefulAdapter()
    store = LiveLifecycleStore(tmp_path / "state.json")
    controller = LiveLifecycleController(adapter, store, trailing_stop_percent=3)
    state = replace(_state(), side="SHORT", initial_stop=103, current_stop=103)
    controller.register(state)

    candles = [
        Candle("BTC/USDT", "2026-01-01T00:00:00Z", 100, 101, 96, 97, 1),
        Candle("BTC/USDT", "2026-01-01T00:01:00Z", 97, 98, 94, 95, 1),
    ]

    new_stop = controller.update_stop_from_candles("p1", candles)
    assert new_stop is not None and 95 < new_stop < 100
    assert adapter.tightened == [new_stop]

    lower_price_candles = candles + [
        Candle("BTC/USDT", "2026-01-01T00:02:00Z", 95, 96, 90, 91, 1),
    ]
    improved = controller.update_stop_from_candles("p1", lower_price_candles)
    assert improved is not None and improved < new_stop
    assert adapter.tightened[-1] == improved


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


def test_monitor_non_hold_decision_still_manages_trailing(tmp_path) -> None:
    adapter = StatefulAdapter()
    controller = LiveLifecycleController(
        adapter, LiveLifecycleStore(tmp_path / "state.json"),
        trailing_stop_percent=3,
    )
    controller.register(_state())
    managed = apply_live_lifecycle_monitor(
        controller, position={"position_id": "p1", "quantity": 1},
        decision={"action": "EXIT", "meta": {}},
        ltf_candles=_candles(),
    )
    assert managed["managed"] is True


def test_store_keeps_existing_open_lifecycle_state(tmp_path) -> None:
    store = LiveLifecycleStore(tmp_path / "state.json")
    controller = LiveLifecycleController(StatefulAdapter(), store, trailing_stop_percent=3)
    controller.register(_state())

    assert store.load()["p1"].position_id == "p1"


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


def _ada_adapter(tmp_path):
    import run_realtime  # noqa: F401  (module wiring must stay importable)

    from app.executor_agent.bitunix_futures_adapter import (
        BitunixCredentials, BitunixFuturesExecutorAdapter, BitunixLiveSafetyGate,
    )

    fake = StatefulAdapter()
    fake.rows = [
        {"id": "tp1", "positionId": "ada", "symbol": "ADAUSDT", "tpPrice": "0.1900", "tpQty": "333"},
        {"id": "tp2", "positionId": "ada", "symbol": "ADAUSDT", "tpPrice": "0.1850", "tpQty": "333"},
        {"id": "tp3", "positionId": "ada", "symbol": "ADAUSDT", "tpPrice": "0.1800", "tpQty": "334"},
        {"id": "sl1", "positionId": "ada", "symbol": "ADAUSDT", "slPrice": "0.1998", "slQty": "1000"},
    ]
    adapter = BitunixFuturesExecutorAdapter(
        BitunixCredentials("test-key", "test-secret"),
        safety_gate=BitunixLiveSafetyGate(enabled=True, dry_run=True),
    )
    adapter.pending_tpsl = fake.pending_tpsl  # type: ignore[method-assign]
    adapter.tighten_stop = fake.tighten_stop  # type: ignore[method-assign]
    adapter.place_lifecycle_take_profit = fake.place_lifecycle_take_profit  # type: ignore[method-assign]
    adapter.record_protection_metadata = lambda **kwargs: None
    adapter._lifecycle_store_path = tmp_path / "lifecycle.json"
    return fake, adapter


class _AdaMarketData:
    def fetch_ohlcv(self, symbol, *, timeframe, limit):
        class R:
            candles = [
                Candle(
                    "ADA/USDT", "2026-01-01T00:00:00Z",
                    0.1900, 0.1905, 0.1896, 0.1896, 1.0,
                )
            ]
        return R()


def _ada_position() -> dict[str, object]:
    return {
        "position_id": "ada", "symbol": "ADAUSDT", "side": "SHORT",
        "entry_price": 0.1962, "stop_loss": 0.1998, "quantity": 1000,
    }


def test_production_wiring_moves_short_stop_with_setting_percent(tmp_path, monkeypatch) -> None:
    """The exact runtime wiring (percent from settings → controller → exchange).

    SHORT entry 0.1962 at 0.1896 with a 3% trailing must tighten the live SL
    from 0.1998 to ~0.195288 even with coordinator=None, no decision, no
    monitor. Guards the production NameError regression.
    """
    import run_realtime

    fake, adapter = _ada_adapter(tmp_path)
    monkeypatch.setattr(
        run_realtime, "resolve_live_bitunix_lifecycle_adapter",
        lambda coordinator: adapter,
    )
    updates = run_realtime.apply_live_trailing_protection(
        coordinator=None,
        trailing_stop_percent=3,
        open_positions_map={"ADAUSDT": _ada_position()},
        market_data=_AdaMarketData(),
        timeframe="5m",
        limit=100,
    )
    assert updates[0]["managed"] is True
    assert "error" not in updates[0]
    assert updates[0]["new_stop"] == pytest.approx(0.1896 * 1.03, abs=1e-9)
    assert fake.tightened == [pytest.approx(0.195288, abs=1e-9)]


def test_production_wiring_never_moves_without_percent_setting(tmp_path, monkeypatch) -> None:
    """Without the trailing percentage, no stop mutation is submitted."""
    import run_realtime

    fake, adapter = _ada_adapter(tmp_path)
    monkeypatch.setattr(
        run_realtime, "resolve_live_bitunix_lifecycle_adapter",
        lambda coordinator: adapter,
    )
    updates = run_realtime.apply_live_trailing_protection(
        coordinator=None,
        trailing_stop_percent=None,
        open_positions_map={"ADAUSDT": _ada_position()},
        market_data=_AdaMarketData(),
        timeframe="5m",
        limit=100,
    )
    assert updates[0]["managed"] is True
    assert updates[0]["new_stop"] is None
    assert fake.tightened == []


def test_production_wiring_fails_closed_without_adapter(monkeypatch) -> None:
    """No adapter (no credentials) is exposed, never silently skipped."""
    import run_realtime

    monkeypatch.setattr(
        run_realtime, "resolve_live_bitunix_lifecycle_adapter",
        lambda coordinator: None,
    )
    updates = run_realtime.apply_live_trailing_protection(
        coordinator=None,
        trailing_stop_percent=3,
        open_positions_map={"ADAUSDT": _ada_position()},
        market_data=_AdaMarketData(),
        timeframe="5m",
        limit=100,
    )
    assert updates[0]["managed"] is False
    assert updates[0]["error"] == "live_trailing_unavailable:no_bitunix_adapter"


def test_live_adapter_resolver_prefers_coordinator_then_falls_back(monkeypatch) -> None:
    """Coordinator adapter wins; otherwise a standalone adapter is built."""
    import run_realtime
    from types import SimpleNamespace

    from app.executor_agent.bitunix_futures_adapter import (
        BitunixCredentials, BitunixFuturesExecutorAdapter, BitunixLiveSafetyGate,
    )

    monkeypatch.setattr(run_realtime, "build_standalone_bitunix_adapter", lambda: "standalone")
    assert run_realtime.resolve_live_bitunix_lifecycle_adapter(None) == "standalone"
    assert run_realtime.resolve_live_bitunix_lifecycle_adapter(
        SimpleNamespace(executor_agent=SimpleNamespace(_exchange=None))
    ) == "standalone"

    adapter = BitunixFuturesExecutorAdapter(
        BitunixCredentials("test-key", "test-secret"),
        safety_gate=BitunixLiveSafetyGate(enabled=True, dry_run=True),
    )
    coordinator = SimpleNamespace(executor_agent=SimpleNamespace(_exchange=adapter))
    assert run_realtime.resolve_live_bitunix_lifecycle_adapter(coordinator) is adapter
