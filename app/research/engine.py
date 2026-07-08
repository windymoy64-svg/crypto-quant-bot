from __future__ import annotations

import math
from collections import defaultdict
from datetime import UTC, datetime
from statistics import mean
from typing import Any, Callable

from app.research.artifacts import ResearchDataset, ResearchEquityPoint, ResearchTrade, parse_datetime


TIMEFRAMES = ["5m", "15m", "1h", "4h", "1d"]
REGIMES = ["Bull", "Bear", "Sideways", "High Volatility", "Low Volatility"]


class StrategyResearchEngine:
    def analyze(self, dataset: ResearchDataset) -> dict[str, Any]:
        trades = dataset.trades
        equity = dataset.equity_curve
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "artifacts": dataset.artifacts,
            "overall_performance": performance_metrics(trades, equity),
            "pair_analysis": ranked_group_analysis(trades, lambda trade: trade.symbol),
            "timeframe_analysis": timeframe_analysis(trades),
            "market_regime_analysis": market_regime_analysis(trades),
            "rule_attribution": rule_attribution(trades),
            "feature_importance_summary": feature_importance_summary(trades, dataset.feature_importance),
            "time_of_day_analysis": time_bucket_analysis(trades, "hour"),
            "day_of_week_analysis": time_bucket_analysis(trades, "weekday"),
            "longest_winning_streak": longest_streak(trades, True),
            "longest_losing_streak": longest_streak(trades, False),
            "trade_duration_analysis": trade_duration_analysis(trades),
            "equity_curve_summary": equity_curve_summary(equity),
        }


def performance_metrics(trades: list[ResearchTrade], equity: list[ResearchEquityPoint] | None = None) -> dict[str, float]:
    equity = equity or []
    wins = [trade.net_pnl for trade in trades if trade.net_pnl > 0]
    losses = [trade.net_pnl for trade in trades if trade.net_pnl < 0]
    net_profit = sum(trade.net_pnl for trade in trades)
    gross_profit = sum(wins)
    gross_loss = sum(losses)
    total = len(trades)
    win_rate = (len(wins) / total) * 100 if total else 0.0
    average_win = mean(wins) if wins else 0.0
    average_loss = mean(losses) if losses else 0.0
    loss_rate = 1 - (len(wins) / total) if total else 0.0
    profit_factor = gross_profit / abs(gross_loss) if gross_loss else gross_profit if gross_profit else 0.0
    max_drawdown = max_drawdown_percent(equity, trades)
    max_drawdown_amount = max_drawdown_value(equity)
    expectancy = ((win_rate / 100) * average_win) - (loss_rate * abs(average_loss)) if total else 0.0
    return {
        "trades": float(total),
        "net_profit": round(net_profit, 6),
        "gross_profit": round(gross_profit, 6),
        "gross_loss": round(gross_loss, 6),
        "win_rate": round(win_rate, 4),
        "profit_factor": round(profit_factor, 6),
        "sharpe": round(sharpe_ratio(trades), 6),
        "sortino": round(sortino_ratio(trades), 6),
        "calmar": round(net_profit / abs(max_drawdown_amount), 6) if max_drawdown_amount else 0.0,
        "recovery_factor": round(net_profit / abs(max_drawdown_amount), 6) if max_drawdown_amount else 0.0,
        "expectancy": round(expectancy, 6),
        "average_win": round(average_win, 6),
        "average_loss": round(average_loss, 6),
        "max_drawdown": round(max_drawdown, 6),
    }


def ranked_group_analysis(trades: list[ResearchTrade], key: Callable[[ResearchTrade], str]) -> list[dict[str, Any]]:
    grouped: dict[str, list[ResearchTrade]] = defaultdict(list)
    for trade in trades:
        grouped[key(trade)].append(trade)
    rows = [{"name": name, **performance_metrics(items)} for name, items in grouped.items()]
    return sorted(rows, key=lambda row: (row["net_profit"], row["win_rate"], row["profit_factor"], row["trades"]), reverse=True)


def timeframe_analysis(trades: list[ResearchTrade]) -> list[dict[str, Any]]:
    rows = ranked_group_analysis([trade for trade in trades if trade.timeframe in TIMEFRAMES], lambda trade: trade.timeframe)
    return sorted(rows, key=lambda row: TIMEFRAMES.index(str(row["name"])))


def market_regime_analysis(trades: list[ResearchTrade]) -> list[dict[str, Any]]:
    known = [trade for trade in trades if trade.market_regime in REGIMES]
    rows = ranked_group_analysis(known, lambda trade: trade.market_regime)
    return sorted(rows, key=lambda row: REGIMES.index(str(row["name"])))


def rule_attribution(trades: list[ResearchTrade]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = defaultdict(lambda: {"contribution": 0.0, "wins": 0, "count": 0, "scores": []})
    for trade in trades:
        for rule in trade.rules:
            name = str(rule.get("rule_id") or rule.get("id") or rule.get("rule_name") or rule.get("name") or "unknown")
            score = _float(rule.get("score", trade.score))
            grouped[name]["contribution"] += trade.net_pnl
            grouped[name]["wins"] += 1 if trade.is_win else 0
            grouped[name]["count"] += 1
            grouped[name]["scores"].append(score)
    rows = []
    for name, data in grouped.items():
        count = int(data["count"])
        rows.append({
            "rule": name,
            "contribution": round(float(data["contribution"]), 6),
            "win_rate": round((int(data["wins"]) / count) * 100, 4) if count else 0.0,
            "average_score": round(mean(data["scores"]), 6) if data["scores"] else 0.0,
            "trigger_frequency": count,
        })
    return sorted(rows, key=lambda row: (row["contribution"], row["win_rate"], row["trigger_frequency"]), reverse=True)


def feature_importance_summary(trades: list[ResearchTrade], artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, float]] = defaultdict(lambda: {"score": 0.0, "count": 0.0})
    for item in artifacts:
        name = str(item.get("feature") or item.get("name") or item.get("category") or "unknown")
        grouped[name]["score"] += _float(item.get("score", item.get("importance", item.get("percentage", 0.0))))
        grouped[name]["count"] += 1
    for trade in trades:
        for item in trade.features:
            name = str(item.get("feature") or item.get("name") or item.get("category") or "unknown")
            grouped[name]["score"] += _float(item.get("score", item.get("importance", item.get("percentage", 0.0))))
            grouped[name]["count"] += 1
    rows = [
        {"feature": name, "score": round(data["score"], 6), "average_score": round(data["score"] / data["count"], 6), "observations": int(data["count"])}
        for name, data in grouped.items()
        if data["count"]
    ]
    return sorted(rows, key=lambda row: (row["score"], row["observations"]), reverse=True)


def time_bucket_analysis(trades: list[ResearchTrade], bucket: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[ResearchTrade]] = defaultdict(list)
    for trade in trades:
        ended = parse_datetime(trade.exit_time) or parse_datetime(trade.entry_time)
        if not ended:
            continue
        name = f"{ended.hour:02d}:00" if bucket == "hour" else ended.strftime("%A")
        grouped[name].append(trade)
    rows = [{"bucket": name, **performance_metrics(items)} for name, items in grouped.items()]
    if bucket == "hour":
        return sorted(rows, key=lambda row: row["bucket"])
    order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    return sorted(rows, key=lambda row: order.index(str(row["bucket"])))


def longest_streak(trades: list[ResearchTrade], winning: bool) -> int:
    longest = 0
    current = 0
    for trade in trades:
        matched = trade.is_win if winning else trade.net_pnl < 0
        current = current + 1 if matched else 0
        longest = max(longest, current)
    return longest


def trade_duration_analysis(trades: list[ResearchTrade]) -> dict[str, float]:
    durations = [trade.duration_seconds for trade in trades if trade.duration_seconds > 0]
    if not durations:
        return {"average_seconds": 0.0, "min_seconds": 0.0, "max_seconds": 0.0, "trades": 0.0}
    return {"average_seconds": round(mean(durations), 6), "min_seconds": round(min(durations), 6), "max_seconds": round(max(durations), 6), "trades": float(len(durations))}


def equity_curve_summary(equity: list[ResearchEquityPoint]) -> dict[str, Any]:
    if not equity:
        return {"points": 0, "starting_equity": 0.0, "ending_equity": 0.0, "peak_equity": 0.0, "trough_equity": 0.0, "max_drawdown": 0.0, "series": []}
    values = [point.equity for point in equity]
    return {
        "points": len(equity),
        "starting_equity": round(values[0], 6),
        "ending_equity": round(values[-1], 6),
        "peak_equity": round(max(values), 6),
        "trough_equity": round(min(values), 6),
        "max_drawdown": round(max_drawdown_percent(equity, []), 6),
        "series": [{"timestamp": point.timestamp, "equity": point.equity, "drawdown_percent": point.drawdown_percent} for point in equity],
    }


def sharpe_ratio(trades: list[ResearchTrade]) -> float:
    returns = [_trade_return(trade) for trade in trades]
    return _ratio(returns, downside_only=False)


def sortino_ratio(trades: list[ResearchTrade]) -> float:
    returns = [_trade_return(trade) for trade in trades]
    return _ratio(returns, downside_only=True)


def max_drawdown_percent(equity: list[ResearchEquityPoint], trades: list[ResearchTrade]) -> float:
    explicit = [abs(point.drawdown_percent) for point in equity if point.drawdown_percent]
    if explicit:
        return max(explicit)
    values = [point.equity for point in equity if point.equity]
    if not values and trades:
        current = 0.0
        values = []
        for trade in trades:
            current += trade.net_pnl
            values.append(current)
    if not values:
        return 0.0
    peak = values[0]
    max_dd = 0.0
    for value in values:
        peak = max(peak, value)
        if peak:
            max_dd = max(max_dd, ((peak - value) / abs(peak)) * 100)
    return max_dd


def max_drawdown_value(equity: list[ResearchEquityPoint]) -> float:
    values = [point.equity for point in equity if point.equity]
    if not values:
        return 0.0
    peak = values[0]
    max_dd = 0.0
    for value in values:
        peak = max(peak, value)
        max_dd = min(max_dd, value - peak)
    return max_dd


def _ratio(values: list[float], downside_only: bool) -> float:
    if len(values) < 2:
        return 0.0
    avg = mean(values)
    sample = [value for value in values if value < 0] if downside_only else values
    if len(sample) < 2:
        return 0.0
    variance = sum((value - (0.0 if downside_only else avg)) ** 2 for value in sample) / (len(sample) - 1)
    deviation = math.sqrt(variance)
    return (avg / deviation) * math.sqrt(len(values)) if deviation else 0.0


def _trade_return(trade: ResearchTrade) -> float:
    if trade.return_percent:
        return trade.return_percent / 100
    return trade.net_pnl


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0