from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class DrawdownCheck:
    valid: bool
    reason: str
    day: str
    day_start_equity: float
    current_equity: float
    drawdown_percent: float
    max_drawdown_percent: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class DailyDrawdownGuard:
    def __init__(self, max_drawdown_percent: float = 5.0) -> None:
        self.max_drawdown_percent = max_drawdown_percent
        self.current_day = ""
        self.day_start_equity = 0.0

    def record_equity(self, timestamp: str, equity: float) -> None:
        day = timestamp[:10]
        if day != self.current_day:
            self.current_day = day
            self.day_start_equity = equity

    def validate(self, timestamp: str, equity: float) -> DrawdownCheck:
        self.record_equity(timestamp, equity)
        drawdown = 0.0
        if self.day_start_equity > 0:
            drawdown = ((self.day_start_equity - equity) / self.day_start_equity) * 100
        valid = drawdown < self.max_drawdown_percent
        reason = "ok" if valid else "daily_drawdown_limit"
        return DrawdownCheck(
            valid=valid,
            reason=reason,
            day=self.current_day,
            day_start_equity=round(self.day_start_equity, 8),
            current_equity=round(equity, 8),
            drawdown_percent=round(max(drawdown, 0.0), 4),
            max_drawdown_percent=self.max_drawdown_percent,
        )