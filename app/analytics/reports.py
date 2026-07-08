from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.analytics.attribution import pair_performance, period_summary, regime_performance, rule_attribution
from app.analytics.equity import EquityCurve
from app.analytics.journal import TradeJournal
from app.analytics.performance import PerformanceMetrics, calculate_performance_metrics
from app.events.events import (
    BacktestFinished,
    PaperBalanceUpdated,
    PaperOrderFilled,
    PaperPositionClosed,
    PortfolioUpdated,
    PositionClosed,
)
from app.events.subscriber import subscribe, unsubscribe


@dataclass(frozen=True)
class AnalyticsConfig:
    enabled: bool = True
    paper_state_path: str = "logs/paper_state.json"
    paper_events_path: str = "logs/paper_events.jsonl"
    backtest_results_dir: str = "logs/backtests"
    output_path: str = "logs/analytics_report.json"
    initial_equity: float = 10_000.0
    periods_per_year: int = 252
    include_event_bus: bool = True
    include_paper_state: bool = True
    include_backtests: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AnalyticsConfig":
        return cls(
            enabled=bool(data.get("enabled", True)),
            paper_state_path=str(data.get("paper_state_path", "logs/paper_state.json")),
            paper_events_path=str(data.get("paper_events_path", "logs/paper_events.jsonl")),
            backtest_results_dir=str(data.get("backtest_results_dir", "logs/backtests")),
            output_path=str(data.get("output_path", "logs/analytics_report.json")),
            initial_equity=float(data.get("initial_equity", 10_000.0)),
            periods_per_year=int(data.get("periods_per_year", 252)),
            include_event_bus=bool(data.get("include_event_bus", True)),
            include_paper_state=bool(data.get("include_paper_state", True)),
            include_backtests=bool(data.get("include_backtests", True)),
        )

    @classmethod
    def from_json(cls, path: str | Path) -> "AnalyticsConfig":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8-sig")))

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class AnalyticsReport:
    config: AnalyticsConfig
    performance: PerformanceMetrics
    journal: dict[str, object]
    equity: dict[str, object]
    pair_performance: dict[str, dict[str, object]]
    regime_performance: dict[str, dict[str, object]]
    rule_attribution: dict[str, dict[str, object]]
    daily: dict[str, dict[str, object]]
    weekly: dict[str, dict[str, object]]
    monthly: dict[str, dict[str, object]]
    sources: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "config": self.config.to_dict(),
            "performance": self.performance.to_dict(),
            "journal": self.journal,
            "equity": self.equity,
            "pair_performance": self.pair_performance,
            "regime_performance": self.regime_performance,
            "rule_attribution": self.rule_attribution,
            "daily": self.daily,
            "weekly": self.weekly,
            "monthly": self.monthly,
            "sources": self.sources,
        }


class AnalyticsEngine:
    def build_report(
        self,
        config: AnalyticsConfig,
        *,
        journal: TradeJournal | None = None,
        equity_curve: EquityCurve | None = None,
    ) -> AnalyticsReport:
        merged_journal = journal or TradeJournal()
        merged_equity = equity_curve or EquityCurve()
        sources: dict[str, object] = {"event_bus": config.include_event_bus}

        if config.include_paper_state:
            paper_journal, paper_equity = self._load_paper(config)
            merged_journal.extend(paper_journal.entries)
            merged_equity.points.extend(paper_equity.points)
            sources["paper_state_path"] = config.paper_state_path
            sources["paper_events_path"] = config.paper_events_path

        if config.include_backtests:
            backtest_journal, backtest_equity, files = self._load_backtests(config)
            merged_journal.extend(backtest_journal.entries)
            merged_equity.points.extend(backtest_equity.points)
            sources["backtest_files"] = files

        return self._report_from_inputs(config, merged_journal, merged_equity, sources)

    def write_report(self, report: AnalyticsReport, path: str | Path | None = None) -> str:
        output_path = Path(path or report.config.output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
        return str(output_path)

    def _report_from_inputs(
        self,
        config: AnalyticsConfig,
        journal: TradeJournal,
        equity_curve: EquityCurve,
        sources: dict[str, object],
    ) -> AnalyticsReport:
        metrics = calculate_performance_metrics(
            journal.entries,
            equity_curve,
            initial_equity=config.initial_equity,
            periods_per_year=config.periods_per_year,
        )
        return AnalyticsReport(
            config=config,
            performance=metrics,
            journal=journal.to_dict(),
            equity=equity_curve.to_dict(),
            pair_performance=pair_performance(journal.entries),
            regime_performance=regime_performance(journal.entries),
            rule_attribution=rule_attribution(journal.entries),
            daily=period_summary(journal.entries, "daily"),
            weekly=period_summary(journal.entries, "weekly"),
            monthly=period_summary(journal.entries, "monthly"),
            sources=sources,
        )

    def _load_paper(self, config: AnalyticsConfig) -> tuple[TradeJournal, EquityCurve]:
        state_path = Path(config.paper_state_path)
        state = _read_json_object(state_path)
        fills = list(state.get("fills", [])) if isinstance(state.get("fills"), list) else []
        if not fills:
            fills = _read_paper_event_fills(Path(config.paper_events_path))
        return TradeJournal.from_paper_fills(fills), EquityCurve.from_paper_state(state)

    def _load_backtests(self, config: AnalyticsConfig) -> tuple[TradeJournal, EquityCurve, list[str]]:
        journal = TradeJournal()
        equity = EquityCurve()
        files: list[str] = []
        directory = Path(config.backtest_results_dir)
        if not directory.exists():
            return journal, equity, files
        for path in sorted(directory.glob("*.json")):
            data = _read_json_object(path)
            trades = data.get("trades") if isinstance(data.get("trades"), list) else []
            equity_rows = data.get("equity_curve") if isinstance(data.get("equity_curve"), list) else []
            journal.extend(TradeJournal.from_backtest_trades(trades).entries)
            equity.points.extend(EquityCurve.from_backtest_equity(equity_rows).points)
            files.append(str(path))
        return journal, equity, files


class AnalyticsEventCollector:
    def __init__(self) -> None:
        self.paper_fills: list[dict[str, object]] = []
        self.paper_closes: list[dict[str, object]] = []
        self.portfolio_snapshots: list[dict[str, object]] = []
        self.backtests: list[dict[str, object]] = []
        self._subscribed = False

    def subscribe(self) -> None:
        if self._subscribed:
            return
        for event_type in self._event_types():
            subscribe(event_type, self.handle)
        self._subscribed = True

    def unsubscribe(self) -> None:
        if not self._subscribed:
            return
        for event_type in self._event_types():
            unsubscribe(event_type, self.handle)
        self._subscribed = False

    def handle(self, event: object) -> None:
        payload = event.to_dict() if hasattr(event, "to_dict") else {}
        event_name = event.__class__.__name__
        if isinstance(event, PaperOrderFilled):
            self.paper_fills.append(event.fill or payload)
        elif isinstance(event, PaperPositionClosed):
            self.paper_closes.append(payload)
        elif isinstance(event, PaperBalanceUpdated):
            self.portfolio_snapshots.append({**event.account, "equity": event.equity, "timestamp": event.timestamp})
        elif isinstance(event, PositionClosed):
            self.paper_closes.append(payload)
        elif isinstance(event, PortfolioUpdated):
            self.portfolio_snapshots.append({**event.portfolio, "equity": event.equity, "timestamp": event.timestamp})
        elif isinstance(event, BacktestFinished):
            self.backtests.append(payload)
        else:
            self.backtests.append({"event_type": event_name, "payload": payload})

    def report(self, config: AnalyticsConfig | None = None) -> AnalyticsReport:
        active_config = config or AnalyticsConfig(include_paper_state=False, include_backtests=False)
        journal = TradeJournal.from_paper_fills(self.paper_fills, source="event_bus")
        equity = EquityCurve.from_portfolio_snapshots(self.portfolio_snapshots, source="event_bus")
        return AnalyticsEngine().build_report(active_config, journal=journal, equity_curve=equity)

    def _event_types(self) -> tuple[type[object], ...]:
        return (
            PaperOrderFilled,
            PaperPositionClosed,
            PaperBalanceUpdated,
            PositionClosed,
            PortfolioUpdated,
            BacktestFinished,
        )


def _read_json_object(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    return data if isinstance(data, dict) else {}


def _read_paper_event_fills(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    fills: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "fill" and isinstance(event.get("payload"), dict):
            fills.append(event["payload"])
    return fills