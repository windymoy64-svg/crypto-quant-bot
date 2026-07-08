from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class EquityPoint:
    timestamp: str
    cash: float
    position_value: float
    equity: float
    drawdown_percent: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class EquityCurveBuilder:
    def __init__(self, initial_equity: float) -> None:
        self.peak_equity = initial_equity
        self.points: list[EquityPoint] = []

    def add(self, timestamp: str, cash: float, position_value: float) -> EquityPoint:
        equity = cash + position_value
        self.peak_equity = max(self.peak_equity, equity)
        drawdown = ((equity - self.peak_equity) / self.peak_equity) * 100 if self.peak_equity else 0.0
        point = EquityPoint(
            timestamp=timestamp,
            cash=round(cash, 8),
            position_value=round(position_value, 8),
            equity=round(equity, 8),
            drawdown_percent=round(drawdown, 4),
        )
        self.points.append(point)
        return point