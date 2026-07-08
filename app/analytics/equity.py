from __future__ import annotations

from dataclasses import asdict, dataclass

from app.analytics.statistics import safe_float


@dataclass(frozen=True)
class AnalyticsEquityPoint:
    timestamp: str
    equity: float
    cash: float = 0.0
    position_value: float = 0.0
    drawdown_percent: float = 0.0
    source: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class EquityCurve:
    def __init__(self, points: list[AnalyticsEquityPoint] | None = None) -> None:
        self.points = points or []

    @classmethod
    def from_backtest_equity(cls, rows: list[dict[str, object]], source: str = "backtest") -> "EquityCurve":
        return cls([_point_from_row(row, source) for row in rows])

    @classmethod
    def from_portfolio_snapshots(cls, rows: list[dict[str, object]], source: str = "portfolio") -> "EquityCurve":
        points: list[AnalyticsEquityPoint] = []
        peak = 0.0
        for row in rows:
            equity = safe_float(row.get("equity"))
            peak = max(peak, equity)
            drawdown = ((equity - peak) / peak) * 100 if peak else 0.0
            points.append(
                AnalyticsEquityPoint(
                    timestamp=str(row.get("timestamp", row.get("updated_at", ""))),
                    equity=round(equity, 8),
                    cash=round(safe_float(row.get("cash", row.get("available_balance"))), 8),
                    position_value=round(safe_float(row.get("position_value", row.get("market_value"))), 8),
                    drawdown_percent=round(safe_float(row.get("drawdown_percent", drawdown)), 4),
                    source=source,
                )
            )
        return cls(points)

    @classmethod
    def from_paper_state(cls, state: dict[str, object], source: str = "paper") -> "EquityCurve":
        account = state.get("account") if isinstance(state.get("account"), dict) else {}
        account_data = account if isinstance(account, dict) else {}
        cash = safe_float(account_data.get("cash"))
        return cls([
            AnalyticsEquityPoint(
                timestamp=str(state.get("updated_at", "")),
                equity=round(cash, 8),
                cash=round(cash, 8),
                source=source,
            )
        ])

    def returns(self) -> list[float]:
        values: list[float] = []
        for previous, current in zip(self.points[:-1], self.points[1:]):
            if previous.equity:
                values.append((current.equity - previous.equity) / previous.equity)
        return values

    def max_drawdown_percent(self) -> float:
        if not self.points:
            return 0.0
        return abs(min(point.drawdown_percent for point in self.points))

    def to_dict(self) -> dict[str, object]:
        return {
            "points": [point.to_dict() for point in self.points],
            "count": len(self.points),
        }


def _point_from_row(row: dict[str, object], source: str) -> AnalyticsEquityPoint:
    return AnalyticsEquityPoint(
        timestamp=str(row.get("timestamp", "")),
        equity=round(safe_float(row.get("equity")), 8),
        cash=round(safe_float(row.get("cash")), 8),
        position_value=round(safe_float(row.get("position_value")), 8),
        drawdown_percent=round(safe_float(row.get("drawdown_percent")), 4),
        source=source,
    )