from __future__ import annotations

from dataclasses import asdict, dataclass

from app.core.models import Candle


@dataclass(frozen=True)
class VolatilityCheck:
    valid: bool
    reason: str
    atr: float
    atr_percent: float
    min_atr_percent: float
    max_atr_percent: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class ATRVolatilityFilter:
    def __init__(self, min_atr_percent: float = 0.0, max_atr_percent: float = 25.0, period: int = 14) -> None:
        self.min_atr_percent = min_atr_percent
        self.max_atr_percent = max_atr_percent
        self.period = period

    def validate(self, candles: list[Candle]) -> VolatilityCheck:
        atr = self._atr(candles)
        close = candles[-1].close if candles else 0.0
        atr_percent = (atr / close) * 100 if close else 0.0
        if atr_percent < self.min_atr_percent:
            return self._check(False, "atr_too_low", atr, atr_percent)
        if atr_percent > self.max_atr_percent:
            return self._check(False, "atr_too_high", atr, atr_percent)
        return self._check(True, "ok", atr, atr_percent)

    def _atr(self, candles: list[Candle]) -> float:
        if len(candles) < 2:
            return 0.0
        window = candles[-(self.period + 1) :]
        true_ranges: list[float] = []
        for previous, current in zip(window[:-1], window[1:]):
            true_ranges.append(
                max(
                    current.high - current.low,
                    abs(current.high - previous.close),
                    abs(current.low - previous.close),
                )
            )
        return sum(true_ranges) / len(true_ranges) if true_ranges else 0.0

    def _check(self, valid: bool, reason: str, atr: float, atr_percent: float) -> VolatilityCheck:
        return VolatilityCheck(
            valid=valid,
            reason=reason,
            atr=round(atr, 8),
            atr_percent=round(atr_percent, 4),
            min_atr_percent=self.min_atr_percent,
            max_atr_percent=self.max_atr_percent,
        )