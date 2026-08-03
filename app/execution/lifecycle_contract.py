"""Shared paper/live position-lifecycle contract.

This module is deliberately exchange-agnostic.  It defines the deterministic
TP geometry and quantities that both the paper engine and live adapters must
use.  Exchange fills, fees and rounding remain adapter responsibilities.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


LIFECYCLE_VERSION = "paper_live_lifecycle_v1"
TP_FRACTIONS = (0.30, 0.30, 0.40)
TP_ROLES = ("take_profit_1", "take_profit_2", "take_profit_3")
REQUIRED_LIVE_CAPABILITIES = (
    "three_stage_tp", "mandatory_stop", "breakeven_modify_in_place",
    "trailing_tighten_only", "hold_tp_management", "partial_reconciliation",
    "decision_exit", "post_mutation_verification",
)


@dataclass(frozen=True)
class LifecycleParityReport:
    compatible: bool
    reasons: tuple[str, ...]
    lifecycle_version: str = LIFECYCLE_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "compatible": self.compatible,
            "reasons": list(self.reasons),
            "lifecycle_version": self.lifecycle_version,
        }


def validate_live_capabilities(capabilities: dict[str, bool]) -> LifecycleParityReport:
    """Return fail-closed readiness with precise missing capabilities."""

    reasons = tuple(
        f"missing_live_capability:{name}"
        for name in REQUIRED_LIVE_CAPABILITIES
        if not bool(capabilities.get(name, False))
    )
    return LifecycleParityReport(not reasons, reasons)


def take_profit_levels(
    *,
    entry: float,
    stop_loss: float,
    side: str,
    planned_levels: Iterable[float | None],
    target_risk_reward: float | None = None,
) -> tuple[float, ...]:
    """Return up to three valid profit-side levels.

    A configured RR creates the same RR/RR+1/RR+2 ladder used by the realtime
    paper engine.  Otherwise valid levels from the deterministic Decision plan
    are preserved.
    """

    normalized_side = str(side).upper()
    is_short = normalized_side in {"SELL", "SHORT"}
    risk = abs(float(entry) - float(stop_loss))
    if target_risk_reward is not None and target_risk_reward > 0 and risk > 0:
        multiples = (
            float(target_risk_reward),
            float(target_risk_reward) + 1.0,
            float(target_risk_reward) + 2.0,
        )
        return tuple(
            round(entry - risk * multiple if is_short else entry + risk * multiple, 8)
            for multiple in multiples
        )

    levels: list[float] = []
    for raw in planned_levels:
        if raw is None:
            continue
        level = float(raw)
        if level <= 0:
            continue
        if (is_short and level >= entry) or (not is_short and level <= entry):
            continue
        levels.append(round(level, 8))
    return tuple(levels[:3])


def take_profit_quantities(initial_quantity: float, level_count: int) -> tuple[float, ...]:
    """Allocate exact initial-size fractions without remaining-size drift."""

    count = max(0, min(int(level_count), len(TP_FRACTIONS)))
    if count == 0 or initial_quantity <= 0:
        return ()
    fractions = TP_FRACTIONS[:count]
    if count < 3:
        # A shortened ladder must still close the entire initial position.
        fractions = (*fractions[:-1], 1.0 - sum(fractions[:-1]))
    quantities = [round(initial_quantity * fraction, 8) for fraction in fractions]
    if quantities:
        quantities[-1] = round(initial_quantity - sum(quantities[:-1]), 8)
    return tuple(quantities)


def validate_entry_order_parity(orders: Iterable[Any]) -> LifecycleParityReport:
    """Pure shadow validator for an executor entry plan (no network calls)."""

    rows = list(orders)
    roles = [str(getattr(row, "meta", {}).get("role", "")) for row in rows]
    reasons: list[str] = []
    entries = [row for row, role in zip(rows, roles) if role == "entry"]
    stops = [row for row, role in zip(rows, roles) if role == "stop_loss"]
    tps = [row for row, role in zip(rows, roles) if role in TP_ROLES]
    if len(entries) != 1:
        reasons.append("exactly_one_entry_required")
    if len(stops) != 1 or not bool(getattr(stops[0], "reduce_only", False)):
        reasons.append("single_reduce_only_stop_required")
    expected_roles = list(TP_ROLES[: len(tps)])
    if [role for role in roles if role in TP_ROLES] != expected_roles:
        reasons.append("tp_roles_must_be_ordered_and_contiguous")
    if len(tps) != 3:
        reasons.append("three_stage_tp_required")
    if any(not bool(getattr(row, "reduce_only", False)) for row in tps):
        reasons.append("take_profits_must_be_reduce_only")
    if entries and tps:
        initial = float(getattr(entries[0], "quantity", 0.0))
        total = sum(float(getattr(row, "quantity", 0.0)) for row in tps)
        if abs(total - initial) > max(1e-8, initial * 1e-8):
            reasons.append("tp_quantity_must_equal_initial_quantity")
    return LifecycleParityReport(not reasons, tuple(reasons))


def execute_exit_gate(
    *,
    position: dict[str, Any],
    decision_action: str,
    urgency: str,
    pnl_ratio: float,
    min_hold_seconds: float = 300.0,
) -> bool:
    """Shared gate for EXIT decisions (paper and live).

    Returns True when it is safe to close now; False to let the position ride.

    Rules:
    - IMMEDIATE: always allows exit unless inside micro BE/noise band.
      After recent fixes we never suppress IMMEDIATE on tiny profit.
    - NEXT_CANDLE: respect minimum hold age AND allow small noise around breakeven.
        • Skip if position age < min_hold_seconds.
        • Skip if -0.3R < pnl_ratio <= 1.0R (small losses up to 0.3R, profits up to 1R).
    """

    from datetime import datetime, UTC

    if str(decision_action).upper() != "EXIT":
        return True

    if urgency.upper() == "IMMEDIATE":
        # Let structure invalidation exits pass through without PnL gating noise.
        return True

    if urgency.upper() != "NEXT_CANDLE":
        return True

    # Check position age
    opened_at_str = position.get("opened_at")
    if opened_at_str:
        try:
            opened_at = datetime.fromisoformat(opened_at_str.replace("Z", "+00:00"))
            age_seconds = (datetime.now(tz=UTC) - opened_at).total_seconds()
            if age_seconds < min_hold_seconds:
                return False
        except (ValueError, AttributeError):
            pass  # proceed cautiously if parse fails

    # Apply PnL bands
    if -0.3 < pnl_ratio <= 1.0:
        return False

    return True


__all__ = [
    "LIFECYCLE_VERSION", "TP_FRACTIONS", "TP_ROLES",
    "LifecycleParityReport", "take_profit_levels", "take_profit_quantities",
    "validate_entry_order_parity", "validate_live_capabilities",
    "REQUIRED_LIVE_CAPABILITIES",
    "execute_exit_gate",
]