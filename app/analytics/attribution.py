from __future__ import annotations

from app.analytics.journal import TradeJournalEntry
from app.analytics.statistics import period_key


def pair_performance(trades: list[TradeJournalEntry]) -> dict[str, dict[str, object]]:
    return _group_performance(trades, lambda trade: trade.pair or trade.symbol)


def regime_performance(trades: list[TradeJournalEntry]) -> dict[str, dict[str, object]]:
    return _group_performance(trades, lambda trade: trade.regime or "unknown")


def rule_attribution(trades: list[TradeJournalEntry]) -> dict[str, dict[str, object]]:
    grouped: dict[str, list[TradeJournalEntry]] = {}
    for trade in trades:
        rules = trade.rules or ["unknown"]
        for rule in rules:
            grouped.setdefault(rule, []).append(trade)
    return {rule: _summary(entries) for rule, entries in grouped.items()}


def period_summary(trades: list[TradeJournalEntry], period: str) -> dict[str, dict[str, object]]:
    return _group_performance(trades, lambda trade: period_key(trade.exit_time, period))


def _group_performance(
    trades: list[TradeJournalEntry],
    key_func,
) -> dict[str, dict[str, object]]:
    grouped: dict[str, list[TradeJournalEntry]] = {}
    for trade in trades:
        grouped.setdefault(str(key_func(trade)), []).append(trade)
    return {key: _summary(entries) for key, entries in sorted(grouped.items())}


def _summary(trades: list[TradeJournalEntry]) -> dict[str, object]:
    wins = [trade for trade in trades if trade.net_pnl > 0]
    losses = [trade for trade in trades if trade.net_pnl < 0]
    gross_profit = sum(trade.net_pnl for trade in wins)
    gross_loss = sum(trade.net_pnl for trade in losses)
    total = sum(trade.net_pnl for trade in trades)
    count = len(trades)
    return {
        "trades": count,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round((len(wins) / count) * 100, 2) if count else 0.0,
        "gross_profit": round(gross_profit, 8),
        "gross_loss": round(gross_loss, 8),
        "net_pnl": round(total, 8),
        "profit_factor": round(gross_profit / abs(gross_loss), 4) if gross_loss else round(gross_profit, 4),
        "average_pnl": round(total / count, 8) if count else 0.0,
    }