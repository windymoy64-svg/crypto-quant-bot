"""Adaptive detection of whether a structure break is still tradeable."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.chart_agent.models import BiasDirection, StructureBreak
from app.core.models import Candle
from app.indicators.technical import atr as compute_atr


@dataclass(frozen=True)
class MomentumPhase:
    phase: str
    break_age_bars: int | None
    extension_atr: float | None
    volume_ratio: float
    atr_pct: float
    atr_value: float
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def detect_momentum_phase(
    candles: list[Candle],
    breaks: list[StructureBreak],
    bias: BiasDirection,
) -> MomentumPhase:
    """Classify the latest break using current volatility and participation."""
    if not candles:
        return MomentumPhase("none", None, None, 0.0, 0.0, 0.0, ("no_candles",))

    current = float(candles[-1].close)
    atr_value = max(float(compute_atr(candles)), 0.0)
    atr_pct = atr_value / current * 100.0 if current > 0 else 0.0
    volumes = [float(c.volume) for c in candles[-20:]]
    baseline = sum(volumes[:-1]) / len(volumes[:-1]) if len(volumes) > 1 else 0.0
    vol_ratio = volumes[-1] / baseline if baseline > 0 else 0.0

    if not breaks or current <= 0 or atr_value <= 0:
        return MomentumPhase(
            "none", None, None, round(vol_ratio, 3), round(atr_pct, 4),
            atr_value, ("no_break_or_atr",),
        )

    latest = max(breaks, key=lambda item: int(item.index))
    age = max(0, len(candles) - 1 - int(latest.index))
    extension = abs(current - float(latest.price)) / atr_value
    # Volatile symbols become extended quickly; quiet symbols get more bars.
    fresh_window = max(1, min(8, round(2.5 / max(atr_pct, 0.05))))
    extension_cap = max(1.25, min(2.5, 1.5 + atr_pct * 0.25))
    direction_ok = latest.direction == bias or bias == "NEUTRAL"
    reasons = [
        f"break_age={age}",
        f"extension_atr={extension:.2f}",
        f"volume_ratio={vol_ratio:.2f}",
    ]

    if not direction_ok:
        phase = "none"
        reasons.append("break_direction_mismatch")
    elif age == 0:
        phase = "initial"
    elif age <= fresh_window and extension <= extension_cap and vol_ratio >= 1.15:
        phase = "fresh"
    elif extension > extension_cap:
        phase = "extended"
    else:
        phase = "consolidating"

    return MomentumPhase(
        phase=phase,
        break_age_bars=age,
        extension_atr=round(extension, 4),
        volume_ratio=round(vol_ratio, 4),
        atr_pct=round(atr_pct, 4),
        atr_value=round(atr_value, 8),
        reasons=tuple(reasons),
    )
