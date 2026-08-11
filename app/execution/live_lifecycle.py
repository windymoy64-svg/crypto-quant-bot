"""Persistent, idempotent live position lifecycle controller."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.core.models import Candle
from app.execution.lifecycle_contract import LIFECYCLE_VERSION, TP_FRACTIONS, TP_ROLES

logger = logging.getLogger(__name__)


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
    peak_price: float | None = None
    trough_price: float | None = None
    trailing_status: str = "inactive"
    trailing_candidate_stop: float | None = None
    trailing_percent: float | None = None
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

    def __init__(
        self,
        adapter: Any,
        store: LiveLifecycleStore | None = None,
        trailing_stop_percent: float | None = None,
    ) -> None:
        self.adapter = adapter
        self.store = store or LiveLifecycleStore()
        self.trailing_stop_percent = trailing_stop_percent

    def register(self, state: LiveLifecycleState) -> None:
        states = self.store.load()
        existing = states.get(state.position_id)
        if existing is not None and existing.symbol != state.symbol:
            raise RuntimeError("position_id_lifecycle_conflict")
        states[state.position_id] = existing or state
        self.store.save(states)

    def register_existing_position(self, position: dict[str, Any]) -> bool:
        """Adopt an open position only when its complete TP ladder is present."""
        position_id = str(position.get("position_id") or "")
        entry = float(position.get("entry_price") or position.get("entry") or 0)
        stop = float(position.get("stop_loss") or 0)
        quantity = float(position.get("quantity") or position.get("remaining_size") or 0)
        if not position_id or entry <= 0 or stop <= 0 or quantity <= 0:
            return False
        rows = self.adapter.pending_tpsl(
            symbol=str(position.get("symbol") or ""), position_id=position_id,
        )
        levels = sorted({
            float(row.get("tpPrice")) for row in rows if float(row.get("tpPrice") or 0) > 0
        })
        if len(levels) > 3:
            levels = levels[:3]
        if str(position.get("side") or "").upper() in {"SHORT", "SELL"}:
            levels = list(reversed(levels))
        self.register(LiveLifecycleState(
            position_id=position_id,
            symbol=str(position.get("symbol") or ""),
            side=str(position.get("side") or ""),
            entry_price=entry,
            initial_stop=stop,
            current_stop=stop,
            initial_quantity=quantity,
            remaining_quantity=quantity,
            tp_levels=levels,
        ))
        record_protection = getattr(self.adapter, "record_protection_metadata", None)
        if callable(record_protection):
            record_protection(
                symbol=str(position.get("symbol") or ""), position_id=position_id,
                side=str(position.get("side") or ""), role="stop_loss", trigger_price=stop,
            )
            for index, level in enumerate(levels[:3], start=1):
                record_protection(
                    symbol=str(position.get("symbol") or ""), position_id=position_id,
                    side=str(position.get("side") or ""),
                    role=f"take_profit_{index}", trigger_price=level,
                )
        return True

    def reconcile(self, position: dict[str, Any]) -> LiveLifecycleState | None:
        """Reconcile partial fills and authoritative TP IDs after restart."""

        position_id = str(position.get("position_id") or "")
        states = self.store.load()
        state = states.get(position_id)
        if state is None:
            return None  # Legacy/manual position: immutable by this controller.
        remaining = float(position.get("quantity") or position.get("remaining_size") or 0)
        if remaining <= 0:
            # Keep the last protection state available for the closed-position
            # reason classifier until the next live-position reconciliation.
            state.remaining_quantity = 0.0
            states[position_id] = state
            self.store.save(states)
            return None
        state.remaining_quantity = remaining
        rows = self.adapter.pending_tpsl(symbol=state.symbol, position_id=position_id)
        exchange_stops = [
            float(row.get("slPrice") or 0)
            for row in rows
            if float(row.get("slPrice") or 0) > 0
        ]
        if len(exchange_stops) == 1:
            # The exchange is authoritative after restart or manual changes.
            # Never calculate a new trailing stop from stale local state.
            state.current_stop = exchange_stops[0]
        active_tp_prices = {round(float(row.get("tpPrice") or 0), 8): row for row in rows if row.get("tpPrice")}
        state.tp_order_ids = {}
        consumed = max(state.initial_quantity - remaining, 0.0)
        cumulative_fraction = 0.0
        for index, level in enumerate(state.tp_levels[:3]):
            role = TP_ROLES[index]
            row = active_tp_prices.get(round(float(level), 8))
            if row is not None:
                state.tp_order_ids[role] = str(row.get("id") or "")
            cumulative_fraction += TP_FRACTIONS[index]
            level_was_consumed = (
                state.initial_quantity > 0
                and consumed + max(state.initial_quantity * 1e-8, 1e-12)
                >= state.initial_quantity * cumulative_fraction
            )
            if row is None and not state.hold_mode and level_was_consumed:
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
        percent = float(self.trailing_stop_percent or 0)
        if percent <= 0 or not candles:
            return None

        is_long = state.side.upper() in {"BUY", "LONG"}
        current = float(candles[-1].close)
        if is_long:
            peak = max(
                [state.peak_price or state.entry_price]
                + [float(candle.high) for candle in candles]
            )
            state.peak_price = peak
            activation_price = state.entry_price * (1 + percent / 100)
            if peak < activation_price:
                states[state.position_id] = state
                self.store.save(states)
                logger.info(
                    "trailing_check symbol=%s side=%s entry=%.6f current=%.6f "
                    "percent=%.4f activation=%.6f active=false",
                    state.symbol, state.side, state.entry_price, current,
                    percent, activation_price,
                )
                return None
            state.trailing_active = True
            candidate = peak * (1 - percent / 100)
            valid_candidate = state.entry_price < candidate
            improving = candidate > state.current_stop
        else:
            trough = min(
                [state.trough_price or state.entry_price]
                + [float(candle.low) for candle in candles]
            )
            state.trough_price = trough
            activation_price = state.entry_price * (1 - percent / 100)
            if trough > activation_price:
                states[state.position_id] = state
                self.store.save(states)
                logger.info(
                    "trailing_check symbol=%s side=%s entry=%.6f current=%.6f "
                    "percent=%.4f activation=%.6f active=false",
                    state.symbol, state.side, state.entry_price, current,
                    percent, activation_price,
                )
                return None
            state.trailing_active = True
            candidate = trough * (1 + percent / 100)
            valid_candidate = candidate < state.entry_price
            improving = candidate < state.current_stop

        if not valid_candidate or not improving:
            states[state.position_id] = state
            self.store.save(states)
            logger.info(
                "trailing_check symbol=%s side=%s entry=%.6f current=%.6f "
                "percent=%.4f activation=%.6f active=true old_stop=%.6f new_stop=%.6f "
                "unchanged=true",
                state.symbol, state.side, state.entry_price, current,
                percent, activation_price, state.current_stop, candidate,
            )
            return None

        previous_stop = state.current_stop
        self.adapter.tighten_stop(
            symbol=state.symbol, position_id=state.position_id, side=state.side,
            new_stop=float(candidate), quantity=state.remaining_quantity,
        )
        state.current_stop = float(candidate)
        states[state.position_id] = state
        self.store.save(states)
        logger.info(
            "trailing_check symbol=%s side=%s entry=%.6f current=%.6f "
            "percent=%.4f activation=%.6f active=true old_stop=%.6f new_stop=%.6f",
            state.symbol, state.side, state.entry_price, current,
            percent, activation_price, previous_stop, state.current_stop,
        )
        return state.current_stop

    def rearm_remaining_take_profits(
        self, position: dict[str, Any],
    ) -> list[str]:
        """Restore missing TP orders after an exchange-side partial close."""
        state = self.reconcile(position)
        if state is None or state.hold_mode:
            return []
        rows = self.adapter.pending_tpsl(
            symbol=state.symbol, position_id=state.position_id,
        )
        active_prices = {
            round(float(row.get("tpPrice") or 0), 8)
            for row in rows if row.get("tpPrice")
        }
        remaining_roles = [
            (index, TP_ROLES[index])
            for index in range(min(3, len(state.tp_levels)))
            if not state.tp_hit[index]
            and round(float(state.tp_levels[index]), 8) not in active_prices
        ]
        if not remaining_roles:
            return []
        self._restore_remaining_take_profits(state, remaining_roles)
        return [role for _, role in remaining_roles]

    def _restore_remaining_take_profits(
        self, state: LiveLifecycleState,
        remaining_roles: list[tuple[int, str]] | None = None,
    ) -> None:
        remaining_roles = remaining_roles or [
            (index, TP_ROLES[index]) for index in range(min(3, len(state.tp_levels)))
            if not state.tp_hit[index]
        ]
        if not remaining_roles:
            return
        total_fraction = sum(TP_FRACTIONS[index] for index, _ in remaining_roles)
        allocated = 0.0
        for offset, (index, role) in enumerate(remaining_roles):
            quantity = (
                round(state.remaining_quantity - allocated, 8)
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
    """Apply one live price observation to a registered live position."""

    position_id = str(position.get("position_id") or "")
    state = controller.reconcile(position)
    if state is None:
        return {"managed": False, "reason": "legacy_or_unregistered_position"}
    meta = decision.get("meta") if isinstance(decision.get("meta"), dict) else {}
    hold_mode = bool(meta.get("hold_mode", False))
    state = controller.set_hold(position_id, hold_mode) if hold_mode else controller.reconcile(position)
    new_stop = controller.update_stop_from_candles(position_id, ltf_candles)
    refreshed = controller.store.load().get(position_id)
    return {
        "managed": True, "position_id": position_id,
        "hold_mode": state.hold_mode, "new_stop": new_stop,
        "trailing_active": bool(refreshed and refreshed.trailing_active),
        "trailing_status": refreshed.trailing_status if refreshed else "unknown",
        "current_stop": refreshed.current_stop if refreshed else state.current_stop,
        "candidate_stop": refreshed.trailing_candidate_stop if refreshed else None,
        "trailing_percent": refreshed.trailing_percent if refreshed else None,
        "lifecycle_version": state.lifecycle_version,
    }


__all__ = [
    "LiveLifecycleController", "LiveLifecycleState", "LiveLifecycleStore",
    "apply_live_lifecycle_monitor",
]
