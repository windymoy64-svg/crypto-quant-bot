# Strategy Validation

This research layer reads existing backtest and paper-trading artifacts and generates reports only. It does not execute trading, alter signals, change scanner behavior, modify rule scoring, or update risk/portfolio/dashboard logic.

## Inputs

- `logs/backtests/*.json` for historical backtest summaries, trades, equity curves, rules, features, timeframes, and regimes when available.
- `logs/paper_state.json` for current paper-trading state and optional fills/trades.
- `logs/paper_trades.jsonl` for paper trade history when present.
- `logs/*feature*importance*.json` for existing feature-importance artifacts when present.

The loader is tolerant of missing artifacts and returns empty sections instead of failing when no backtests exist.

## Outputs

Run:

```bash
python run_research.py
```

Generated files:

- `reports/strategy_report.json`
- `reports/strategy_report.html`
- `reports/strategy_report.csv`

## Reports

- Overall performance: net profit, gross profit, gross loss, win rate, profit factor, Sharpe, Sortino, Calmar, recovery factor, expectancy, average win, average loss, max drawdown.
- Pair analysis ranked by net profit, win rate, profit factor, and number of trades.
- Timeframe analysis for `5m`, `15m`, `1h`, `4h`, and `1d` when data is available.
- Market regime analysis for Bull, Bear, Sideways, High Volatility, and Low Volatility when data is available.
- Rule attribution by contribution, win rate, average score, and trigger frequency.
- Feature importance summary from existing feature-importance fields/artifacts.
- Time-of-day and day-of-week analysis.
- Longest winning and losing streaks.
- Trade duration analysis.
- Equity curve summary.

## HTML Visualization

`strategy_report.html` is a static ECharts report. It contains charts only and requires no backend changes.

## Research Boundary

- No trading execution.
- No scanner changes.
- No rule engine changes.
- No risk engine changes.
- No portfolio changes.
- No dashboard changes.
- No signal mutation.