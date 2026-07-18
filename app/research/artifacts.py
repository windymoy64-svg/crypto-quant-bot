from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ResearchTrade:
    symbol: str
    timeframe: str
    entry_time: str
    exit_time: str
    net_pnl: float
    gross_pnl: float = 0.0
    fees: float = 0.0
    return_percent: float = 0.0
    score: float = 0.0
    market_regime: str = "unknown"
    rules: list[dict[str, Any]] = field(default_factory=list)
    features: list[dict[str, Any]] = field(default_factory=list)
    source: str = "unknown"

    @property
    def is_win(self) -> bool:
        return self.net_pnl > 0

    @property
    def duration_seconds(self) -> float:
        started = parse_datetime(self.entry_time)
        ended = parse_datetime(self.exit_time)
        if not started or not ended:
            return 0.0
        return max((ended - started).total_seconds(), 0.0)


@dataclass(frozen=True)
class ResearchEquityPoint:
    timestamp: str
    equity: float
    drawdown_percent: float = 0.0
    source: str = "unknown"


@dataclass(frozen=True)
class ResearchDataset:
    trades: list[ResearchTrade]
    equity_curve: list[ResearchEquityPoint]
    feature_importance: list[dict[str, Any]]
    artifacts: list[str]


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def load_research_dataset(logs_dir: str | Path = "logs") -> ResearchDataset:
    base = Path(logs_dir)
    trades: list[ResearchTrade] = []
    equity: list[ResearchEquityPoint] = []
    features: list[dict[str, Any]] = []
    artifacts: list[str] = []

    for path in sorted((base / "backtests").glob("*.json")):
        data = _read_json(path)
        if not isinstance(data, dict):
            continue
        artifacts.append(str(path))
        config = data.get("config", {}) if isinstance(data.get("config"), dict) else {}
        symbol = str(data.get("symbol") or config.get("symbol") or "unknown")
        timeframe = str(data.get("timeframe") or config.get("timeframe") or "unknown")
        trades.extend(_extract_trades(data.get("trades", []), symbol, timeframe, str(path)))
        equity.extend(_extract_equity(data.get("equity_curve", []), str(path)))
        features.extend(_extract_feature_importance(data))

    paper_state = _read_json(base / "paper_state.json")
    if isinstance(paper_state, dict):
        artifacts.append(str(base / "paper_state.json"))
        trades.extend(_extract_trades(paper_state.get("fills", []), "unknown", "paper", "paper_state"))
        trades.extend(_extract_trades(paper_state.get("trades", []), "unknown", "paper", "paper_state"))
        equity.extend(_extract_paper_equity(paper_state))

    paper_trades = base / "paper_trades.jsonl"
    if paper_trades.exists():
        artifacts.append(str(paper_trades))
        trades.extend(_extract_trades(_read_jsonl(paper_trades), "unknown", "paper", str(paper_trades)))

    for path in sorted(base.glob("*feature*importance*.json")):
        data = _read_json(path)
        if isinstance(data, dict):
            artifacts.append(str(path))
            features.extend(_extract_feature_importance(data))
        elif isinstance(data, list):
            artifacts.append(str(path))
            features.extend(item for item in data if isinstance(item, dict))

    trades.sort(key=lambda trade: trade.exit_time or trade.entry_time)
    equity.sort(key=lambda point: point.timestamp)
    return ResearchDataset(trades=trades, equity_curve=equity, feature_importance=features, artifacts=artifacts)


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        with path.open(encoding="utf-8-sig") as file:
            return json.load(file)
    except json.JSONDecodeError:
        return None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8-sig") as file:
        for line in file:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                rows.append(item)
    return rows


def _extract_trades(rows: Any, default_symbol: str, default_timeframe: str, source: str) -> list[ResearchTrade]:
    if not isinstance(rows, list):
        return []
    trades: list[ResearchTrade] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        pnl = _float(row.get("net_pnl", row.get("pnl", row.get("profit", 0.0))))
        trades.append(
            ResearchTrade(
                symbol=str(row.get("symbol") or row.get("pair") or default_symbol),
                timeframe=str(row.get("timeframe") or default_timeframe),
                entry_time=str(row.get("entry_time") or row.get("opened_at") or row.get("created_at") or ""),
                exit_time=str(row.get("exit_time") or row.get("closed_at") or row.get("updated_at") or row.get("timestamp") or ""),
                net_pnl=pnl,
                gross_pnl=_float(row.get("gross_pnl", pnl)),
                fees=_float(row.get("fees", row.get("fee", 0.0))),
                return_percent=_float(row.get("return_percent", row.get("return_pct", 0.0))),
                score=_float(row.get("score", row.get("average_score", 0.0))),
                market_regime=_regime(row),
                rules=_list_of_dicts(row.get("rules") or row.get("rule_results") or row.get("triggered_rules")),
                features=_list_of_dicts(row.get("features") or row.get("feature_importance")),
                source=source,
            )
        )
    return trades


def _extract_equity(rows: Any, source: str) -> list[ResearchEquityPoint]:
    if not isinstance(rows, list):
        return []
    points: list[ResearchEquityPoint] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        points.append(
            ResearchEquityPoint(
                timestamp=str(row.get("timestamp") or row.get("time") or ""),
                equity=_float(row.get("equity", row.get("balance", 0.0))),
                drawdown_percent=_float(row.get("drawdown_percent", row.get("drawdown", 0.0))),
                source=source,
            )
        )
    return points


def _extract_paper_equity(state: dict[str, Any]) -> list[ResearchEquityPoint]:
    timestamp = str(state.get("updated_at") or state.get("created_at") or "")
    equity = _float(state.get("equity", state.get("balance", 0.0)))
    return [ResearchEquityPoint(timestamp=timestamp, equity=equity, source="paper_state")] if timestamp or equity else []


def _extract_feature_importance(data: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = [data.get("feature_importance"), data.get("features")]
    analytics = data.get("analytics") if isinstance(data.get("analytics"), dict) else {}
    candidates.append(analytics.get("feature_importance"))
    output: list[dict[str, Any]] = []
    for candidate in candidates:
        if isinstance(candidate, list):
            output.extend(item for item in candidate if isinstance(item, dict))
    return output


def _regime(row: dict[str, Any]) -> str:
    value = row.get("market_regime") or row.get("regime") or row.get("market_state") or "unknown"
    text = str(value).strip().lower().replace("_", " ")
    if "bull" in text:
        return "Bull"
    if "bear" in text:
        return "Bear"
    if "side" in text or "range" in text:
        return "Sideways"
    if "high" in text and "vol" in text:
        return "High Volatility"
    if "low" in text and "vol" in text:
        return "Low Volatility"
    return str(value).strip() or "unknown"


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0