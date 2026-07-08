from __future__ import annotations

from dataclasses import asdict, dataclass
from math import sqrt

from app.analytics.equity import EquityCurve
from app.analytics.journal import TradeJournalEntry
from app.analytics.statistics import downside_stddev, mean, round_float, sample_stddev


@dataclass(frozen=True)
class PerformanceMetrics:
    trades: int
    wins: int
    losses: int
    win_rate: float
    gross_profit: float
    gross_loss: float
    net_profit: float
    profit_factor: float
    average_win: float
    average_loss: float
    expectancy: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    recovery_factor: float
    max_drawdown_percent: float
    final_equity: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def calculate_performance_metrics(
    trades: list[TradeJournalEntry],
    equity_curve: EquityCurve | None = None,
    *,
    initial_equity: float = 0.0,
    periods_per_year: int = 252,
) -> PerformanceMetrics:
    wins = [trade.net_pnl for trade in trades if trade.net_pnl > 0]
    losses = [trade.net_pnl for trade in trades if trade.net_pnl < 0]
    gross_profit = sum(wins)
    gross_loss = sum(losses)
    net_profit = sum(trade.net_pnl for trade in trades)
    trade_count = len(trades)
    win_rate = (len(wins) / trade_count) * 100 if trade_count else 0.0
    average_win = gross_profit / len(wins) if wins else 0.0
    average_loss = gross_loss / len(losses) if losses else 0.0
    loss_rate = len(losses) / trade_count if trade_count else 0.0
    expectancy = ((win_rate / 100) * average_win) - (loss_rate * abs(average_loss)) if trade_count else 0.0
    profit_factor = gross_profit / abs(gross_loss) if gross_loss else gross_profit if gross_profit else 0.0

    equity = equity_curve or EquityCurve()
    returns = equity.returns() or _returns_from_trades(trades)
    max_drawdown_percent = equity.max_drawdown_percent()
    if max_drawdown_percent == 0.0:
        max_drawdown_percent = _max_drawdown_from_trades(trades, initial_equity)
    final_equity = equity.points[-1].equity if equity.points else initial_equity + net_profit
    annualized_return = _annualized_return(initial_equity, final_equity, len(returns), periods_per_year)

    return PerformanceMetrics(
        trades=trade_count,
        wins=len(wins),
        losses=len(losses),
        win_rate=round_float(win_rate, 2),
        gross_profit=round_float(gross_profit, 8),
        gross_loss=round_float(gross_loss, 8),
        net_profit=round_float(net_profit, 8),
        profit_factor=round_float(profit_factor, 4),
        average_win=round_float(average_win, 8),
        average_loss=round_float(average_loss, 8),
        expectancy=round_float(expectancy, 8),
        sharpe_ratio=round_float(_sharpe(returns, periods_per_year), 4),
        sortino_ratio=round_float(_sortino(returns, periods_per_year), 4),
        calmar_ratio=round_float(_calmar(annualized_return, max_drawdown_percent), 4),
        recovery_factor=round_float(_recovery_factor(net_profit, max_drawdown_percent, initial_equity), 4),
        max_drawdown_percent=round_float(max_drawdown_percent, 4),
        final_equity=round_float(final_equity, 8),
    )


def _returns_from_trades(trades: list[TradeJournalEntry]) -> list[float]:
    return [trade.return_percent / 100 for trade in trades if trade.return_percent]


def _max_drawdown_from_trades(trades: list[TradeJournalEntry], initial_equity: float) -> float:
    if initial_equity <= 0:
        return 0.0
    equity = initial_equity
    peak = initial_equity
    max_drawdown = 0.0
    for trade in trades:
        equity += trade.net_pnl
        peak = max(peak, equity)
        drawdown = ((equity - peak) / peak) * 100 if peak else 0.0
        max_drawdown = min(max_drawdown, drawdown)
    return abs(max_drawdown)


def _sharpe(returns: list[float], periods_per_year: int) -> float:
    volatility = sample_stddev(returns)
    return (mean(returns) / volatility) * sqrt(periods_per_year) if volatility else 0.0


def _sortino(returns: list[float], periods_per_year: int) -> float:
    downside = downside_stddev(returns)
    return (mean(returns) / downside) * sqrt(periods_per_year) if downside else 0.0


def _annualized_return(initial_equity: float, final_equity: float, periods: int, periods_per_year: int) -> float:
    if initial_equity <= 0 or final_equity <= 0 or periods <= 0:
        return 0.0
    return (final_equity / initial_equity) ** (periods_per_year / periods) - 1


def _calmar(annualized_return: float, max_drawdown_percent: float) -> float:
    drawdown = max_drawdown_percent / 100
    return annualized_return / drawdown if drawdown else 0.0


def _recovery_factor(net_profit: float, max_drawdown_percent: float, initial_equity: float) -> float:
    drawdown_amount = initial_equity * (max_drawdown_percent / 100)
    return net_profit / drawdown_amount if drawdown_amount else 0.0