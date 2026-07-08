from __future__ import annotations

import argparse

from app.backtest.engine import BacktestConfig, HistoricalBacktestEngine
from app.backtest.report import BacktestReporter


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run historical OHLCV backtest")
    parser.add_argument("--symbol", default="BTC/USDT")
    parser.add_argument("--exchange", default="binance")
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--limit", type=int, default=300)
    parser.add_argument("--initial-cash", type=float, default=10_000.0)
    parser.add_argument("--position-size-percent", type=float, default=95.0)
    parser.add_argument("--fee-rate", type=float, default=0.001)
    parser.add_argument("--min-window", type=int, default=30)
    parser.add_argument("--maker-fee-rate", type=float, default=0.0002)
    parser.add_argument("--taker-fee-rate", type=float, default=0.001)
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--spread-bps", type=float, default=2.0)
    parser.add_argument("--latency-candles", type=int, default=0)
    parser.add_argument("--max-fill-ratio", type=float, default=1.0)
    parser.add_argument("--min-fill-ratio", type=float, default=0.25)
    parser.add_argument("--risk-per-trade-percent", type=float, default=1.0)
    parser.add_argument("--max-exposure-percent", type=float, default=95.0)
    parser.add_argument("--max-open-positions", type=int, default=1)
    parser.add_argument("--max-daily-drawdown-percent", type=float, default=5.0)
    parser.add_argument("--min-risk-reward", type=float, default=1.2)
    parser.add_argument("--min-atr-percent", type=float, default=0.0)
    parser.add_argument("--max-atr-percent", type=float, default=25.0)
    parser.add_argument("--rules-path", default="configs/rules.json")
    parser.add_argument("--weights-path", default=None)
    parser.add_argument("--output-dir", default="logs/backtests")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = BacktestConfig(
        symbol=args.symbol,
        exchange=args.exchange,
        timeframe=args.timeframe,
        limit=args.limit,
        initial_cash=args.initial_cash,
        position_size_percent=args.position_size_percent,
        fee_rate=args.fee_rate,
        min_window=args.min_window,
        rules_path=args.rules_path,
        weights_path=args.weights_path,
        maker_fee_rate=args.maker_fee_rate,
        taker_fee_rate=args.taker_fee_rate,
        slippage_basis_points=args.slippage_bps,
        spread_basis_points=args.spread_bps,
        latency_candles=args.latency_candles,
        max_fill_ratio=args.max_fill_ratio,
        min_fill_ratio=args.min_fill_ratio,
        risk_per_trade_percent=args.risk_per_trade_percent,
        max_exposure_percent=args.max_exposure_percent,
        max_open_positions=args.max_open_positions,
        max_daily_drawdown_percent=args.max_daily_drawdown_percent,
        min_risk_reward=args.min_risk_reward,
        min_atr_percent=args.min_atr_percent,
        max_atr_percent=args.max_atr_percent,
    )
    result = HistoricalBacktestEngine().run(config)
    reporter = BacktestReporter(args.output_dir)
    paths = reporter.write(result)
    print(reporter.to_console(result, paths))


if __name__ == "__main__":
    main()