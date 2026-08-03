"""Persistent, idempotent live position lifecycle controller."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.core.models import Candle
from app.execution.lifecycle_contract import LIFECYCLE_VERSION, TP_FRACTIONS, TP_ROLES
from app.strategies.acr_engine_bridge import compute_acr_trailing_stop


@dataclass
class LiveLifecycleState:
    position_id: str
    symbol: str
    side: str
    entry_price: float
    initial_stop: float
    current_stop: float
    initial_quantity: float
    remaining_quantity: float
    tp_levels: list[float]
    strategy_version: dict[str, Any] | None = None
    lifecycle_version: str = LIFECYCLE_VERSION
    hold_mode: bool = False
    trailing_active: bool = False
    tp_hit: list[bool] = field(default_factory=lambda: [False, False, False])
    tp_order_ids: dict[str, str] = field(default_factory=dict)


class LiveLifecycleStore:
    def __init__(self, path: str | Path = "logs/bitunix_live_lifecycle.json") -> None:
        self.path = Path(path)

    def load(self) -> dict[str, LiveLifecycleState]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        rows = payload.get("positions", {}) if isinstance(payload, dict) else {}
        result: dict[str, LiveLifecycleState] = {}
        for key, raw in rows.items():
            if not isinstance(raw, dict) or raw.get("lifecycle_version") != LIFECYCLE_VERSION:
                continue
            try:
                result[str(key)] = LiveLifecycleState(**raw)
            except (TypeError, ValueError):
                continue
        return result

    def save(self, states: dict[str, LiveLifecycleState]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps({
            "positions": {key: asdict(value) for key, value in states.items()}
        }, indent=2), encoding="utf-8")
        temporary.replace(self.path)


class LiveLifecycleController:
    """Manage only explicitly registered lifecycle-v1 positions."""

    def __init__(self, adapter: Any, store: LiveLifecycleStore | None = None) -> None:
        self.adapter = adapter
        self.store = store or LiveLifecycleStore()

    def register(self, state: LiveLifecycleState) -> None:
        states = self.store.load()
        existing = states.get(state.position_id)
        if existing is not None and existing.symbol != state.symbol:
            raise RuntimeError("position_id_lifecycle_conflict")
        states[state.position_id] = existing or state
        self.store.save(states)

    def reconcile(self, position: dict[str, Any]) -> LiveLifecycleState | None:
        """Reconcile partial fills and authoritative TP IDs after restart."""

        position_id = str(position.get("position_id") or "")
        states = self.store.load()
        state = states.get(position_id)
        if state is None:
            return None  # Legacy/manual position: immutable by this controller.
        remaining = float(position.get("quantity") or position.get("remaining_size") or 0)
        if remaining <= 0:
            states.pop(position_id, None)
            self.store.save(states)
            return None
        state.remaining_quantity = remaining
        rows = self.adapter.pending_tpsl(symbol=state.symbol, position_id=position_id)
        active_tp_prices = {round(float(row.get("tpPrice") or 0), 8): row for row in rows if row.get("tpPrice")}
        state.tp_order_ids = {}
        for index, level in enumerate(state.tp_levels[:3]):
            role = TP_ROLES[index]
            row = active_tp_prices.get(round(float(level), 8))
            if row is not None:
                state.tp_order_ids[role] = str(row.get("id") or "")
            elif not state.hold_mode:
                state.tp_hit[index] = True
        states[position_id] = state
        self.store.save(states)
        return state

    def set_hold(self, position_id: str, enabled: bool) -> LiveLifecycleState:
        states = self.store.load()
        state = states.get(str(position_id))
        if state is None:
            raise RuntimeError("lifecycle_position_not_registered")
        if state.hold_mode == enabled:
            return state
        if enabled:
            # Cancel bot-owned TPs only. SL IDs are never stored in tp_order_ids.
            for order_id in list(state.tp_order_ids.values()):
                self.adapter.cancel_tpsl_order(symbol=state.symbol, order_id=order_id)
            state.tp_order_ids = {}
            state.hold_mode = True
        else:
            state.hold_mode = False
            self._restore_remaining_take_profits(state)
        states[state.position_id] = state
        self.store.save(states)
        return state

    def update_stop_from_candles(
        self, position_id: str, candles: list[Candle], *, buffer_pct: float = 0.002,
    ) -> float | None:
        states = self.store.load()
        state = states.get(str(position_id))
        if state is None:
            return None
        synthetic = {
            "side": state.side, "entry": state.entry_price,
            "trailing_stop_loss": state.current_stop,
        }
        candidate = compute_acr_trailing_stop(synthetic, candles, buffer_pct=buffer_pct)
        # HOLD gets BE protection at >=1R even before a clean swing appears.
        if state.hold_mode and candles:
            current = float(candles[-1].close)
            risk = abs(state.entry_price - state.initial_stop)
            favorable = (
                current >= state.entry_price + risk
                if state.side.upper() in {"BUY", "LONG"}
                else current <= state.entry_price - risk
            )
            if favorable:
                candidate = max(candidate or state.entry_price, state.entry_price) if state.side.upper() in {"BUY", "LONG"} else min(candidate or state.entry_price, state.entry_price)
        if candidate is None:
            return None
        self.adapter.tighten_stop(
            symbol=state.symbol, position_id=state.position_id, side=state.side,
            new_stop=float(candidate), quantity=state.remaining_quantity,
        )
        state.current_stop = float(candidate)
        state.trailing_active = True
        states[state.position_id] = state
        self.store.save(states)
        return state.current_stop

    def _restore_remaining_take_profits(self, state: LiveLifecycleState) -> None:
        remaining_roles = [
            (index, TP_ROLES[index]) for index in range(min(3, len(state.tp_levels)))
            if not state.tp_hit[index]
        ]
        if not remaining_roles:
            return
        total_fraction = sum(TP_FRACTIONS[index] for index, _ in remaining_roles)
        allocated = 0.0
        for offset, (index, role) in enumerate(remaining_roles):
            quantity = (
                state.remaining_quantity - allocated
                if offset == len(remaining_roles) - 1
                else round(state.remaining_quantity * TP_FRACTIONS[index] / total_fraction, 8)
            )
            result = self.adapter.place_lifecycle_take_profit(
                symbol=state.symbol, position_id=state.position_id,
                side="SELL" if state.side.upper() in {"BUY", "LONG"} else "BUY",
                role=role, price=state.tp_levels[index], quantity=quantity,
            )
            if result.status == "REJECTED":
                raise RuntimeError(f"restore_tp_failed:{role}:{result.reason}")
            allocated += quantity
        # IDs are populated by authoritative reconcile, never guessed from POST.


def apply_live_lifecycle_monitor(
    controller: LiveLifecycleController,
    *,
    position: dict[str, Any],
    decision: dict[str, Any],
    ltf_candles: list[Candle],
) -> dict[str, Any]:
    """Apply one agent HOLD observation to a registered live position."""

    position_id = str(position.get("position_id") or "")
    state = controller.reconcile(position)
    if state is None:
        return {"managed": False, "reason": "legacy_or_unregistered_position"}
    if str(decision.get("action") or "").upper() != "HOLD":
        return {"managed": False, "reason": "decision_not_hold"}
    meta = decision.get("meta") if isinstance(decision.get("meta"), dict) else {}
    hold_mode = bool(meta.get("hold_mode", not bool(meta.get("tp1_enabled", True))))
    state = controller.set_hold(position_id, hold_mode)
    new_stop = controller.update_stop_from_candles(position_id, ltf_candles)
    return {
        "managed": True, "position_id": position_id,
        "hold_mode": state.hold_mode, "new_stop": new_stop,
        "lifecycle_version": state.lifecycle_version,
    }


__all__ = [
    "LiveLifecycleController", "LiveLifecycleState", "LiveLifecycleStore",
    "apply_live_lifecycle_monitor",
]