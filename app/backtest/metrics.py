from __future__ import annotations

from math import sqrt

from app.backtest.equity import EquityPoint
from app.backtest.trade import BacktestTrade


def calculate_backtest_metrics(
    trades: list[BacktestTrade],
    equity_curve: list[EquityPoint],
    initial_cash: float,
) -> dict[str, float]:
    final_equity = equity_curve[-1].equity if equity_curve else initial_cash
    profit = final_equity - initial_cash
    wins = [trade.net_pnl for trade in trades if trade.net_pnl > 0]
    losses = [trade.net_pnl for trade in trades if trade.net_pnl < 0]
    trade_count = len(trades)
    gross_profit = sum(wins)
    gross_loss = sum(losses)
    average_win = gross_profit / len(wins) if wins else 0.0
    average_loss = gross_loss / len(losses) if losses else 0.0
    winrate = (len(wins) / trade_count) * 100 if trade_count else 0.0
    lossrate = 1 - (len(wins) / trade_count) if trade_count else 0.0
    profit_factor = gross_profit / abs(gross_loss) if gross_loss else gross_profit if gross_profit else 0.0
    expectancy = ((winrate / 100) * average_win) - (lossrate * abs(average_loss)) if trade_count else 0.0

    return {
        "trades": float(trade_count),
        "winrate": round(winrate, 2),
        "profit": round(profit, 2),
        "max_drawdown": round(_max_drawdown(equity_curve), 2),
        "sharpe": round(_sharpe(equity_curve), 4),
        "profit_factor": round(profit_factor, 4),
        "average_win": round(average_win, 2),
        "average_loss": round(average_loss, 2),
        "expectancy": round(expectancy, 2),
        "final_equity": round(final_equity, 2),
    }


def _max_drawdown(equity_curve: list[EquityPoint]) -> float:
    if not equity_curve:
        return 0.0
    return abs(min(point.drawdown_percent for point in equity_curve))


def _sharpe(equity_curve: list[EquityPoint]) -> float:
    if len(equity_curve) < 2:
        return 0.0

    returns: list[float] = []
    for previous, current in zip(equity_curve[:-1], equity_curve[1:]):
        if previous.equity:
            returns.append((current.equity - previous.equity) / previous.equity)

    if len(returns) < 2:
        return 0.0

    average_return = sum(returns) / len(returns)
    variance = sum((value - average_return) ** 2 for value in returns) / (len(returns) - 1)
    stddev = sqrt(variance)
    return (average_return / stddev) * sqrt(len(returns)) if stddev else 0.0