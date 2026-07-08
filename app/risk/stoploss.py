from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class StopLossCheck:
    valid: bool
    reason: str
    distance: float
    distance_percent: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class StopLossValidator:
    def validate_long(self, entry: float, stop_loss: float) -> StopLossCheck:
        if entry <= 0 or stop_loss <= 0:
            return StopLossCheck(False, "invalid_price", 0.0, 0.0)
        distance = entry - stop_loss
        distance_percent = (distance / entry) * 100 if entry else 0.0
        if distance <= 0:
            return StopLossCheck(False, "stop_loss_not_below_entry", round(distance, 8), round(distance_percent, 4))
        return StopLossCheck(True, "ok", round(distance, 8), round(distance_percent, 4))