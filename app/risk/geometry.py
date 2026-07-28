"""Single deterministic geometry gate for every entry-plan source."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from math import isfinite
from typing import Any


DEFAULT_MIN_RR = 2.0
DEFAULT_MIN_SL_PCT = 0.35
DEFAULT_MAX_SL_PCT = 4.5


@dataclass(frozen=True)
class EntryGeometryValidation:
    valid: bool
    reasons: list[str] = field(default_factory=list)
    risk_reward: float = 0.0
    sl_pct: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_entry_geometry(
    *,
    side: str,
    entry: float,
    stop_loss: float,
    take_profit: float,
    min_rr: float = DEFAULT_MIN_RR,
    min_sl_pct: float = DEFAULT_MIN_SL_PCT,
    max_sl_pct: float = DEFAULT_MAX_SL_PCT,
) -> EntryGeometryValidation:
    """Validate positive prices, directional sides, SL distance, and TP1 RR."""
    direction = str(side or "").upper()
    is_long = direction in {"BUY", "LONG"}
    is_short = direction in {"SELL", "SHORT"}
    reasons: list[str] = []

    values = (entry, stop_loss, take_profit)
    if not all(isfinite(float(value)) and float(value) > 0 for value in values):
        return EntryGeometryValidation(False, ["invalid_non_positive_or_non_finite_levels"])
    if not is_long and not is_short:
        return EntryGeometryValidation(False, [f"invalid_side={direction or 'EMPTY'}"])

    if is_long:
        if stop_loss >= entry:
            reasons.append("long_sl_not_below_entry")
        if take_profit <= entry:
            reasons.append("long_tp_not_above_entry")
    else:
        if stop_loss <= entry:
            reasons.append("short_sl_not_above_entry")
        if take_profit >= entry:
            reasons.append("short_tp_not_below_entry")

    risk = abs(entry - stop_loss)
    sl_pct = risk / entry * 100.0
    if sl_pct < min_sl_pct:
        reasons.append(f"sl_too_tight={sl_pct:.2f}%")
    if sl_pct > max_sl_pct:
        reasons.append(f"sl_too_wide={sl_pct:.2f}%")

    reward = abs(take_profit - entry)
    risk_reward = reward / risk if risk > 0 else 0.0
    if risk_reward + 1e-12 < min_rr:
        reasons.append(f"rr_too_low={risk_reward:.2f}<{min_rr:.2f}")

    return EntryGeometryValidation(
        valid=not reasons,
        reasons=reasons,
        risk_reward=round(risk_reward, 4),
        sl_pct=round(sl_pct, 4),
    )