from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ExposureCheck:
    valid: bool
    reason: str
    current_exposure: float
    max_exposure: float
    open_positions: int
    max_open_positions: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class ExposureGuard:
    def __init__(self, max_exposure_percent: float = 95.0, max_open_positions: int = 1) -> None:
        self.max_exposure_percent = max_exposure_percent
        self.max_open_positions = max_open_positions

    def max_exposure(self, equity: float) -> float:
        return max(equity, 0.0) * (max(self.max_exposure_percent, 0.0) / 100)

    def validate(self, open_positions: int, current_exposure: float, equity: float) -> ExposureCheck:
        max_exposure = self.max_exposure(equity)
        if open_positions >= self.max_open_positions:
            return ExposureCheck(False, "max_open_positions", current_exposure, max_exposure, open_positions, self.max_open_positions)
        if current_exposure >= max_exposure:
            return ExposureCheck(False, "max_exposure", current_exposure, max_exposure, open_positions, self.max_open_positions)
        return ExposureCheck(True, "ok", current_exposure, max_exposure, open_positions, self.max_open_positions)