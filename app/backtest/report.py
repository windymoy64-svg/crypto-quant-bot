from __future__ import annotations

import csv
import json
from pathlib import Path

from app.backtest.engine import BacktestResult


class BacktestReporter:
    def __init__(self, output_dir: str | Path = "logs/backtests") -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def write(self, result: BacktestResult) -> dict[str, str]:
        stem = self._artifact_stem(result)
        json_path = self.output_dir / f"{stem}.json"
        trades_csv_path = self.output_dir / f"{stem}_trades.csv"
        equity_csv_path = self.output_dir / f"{stem}_equity.csv"

        json_path.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
        self._write_csv(trades_csv_path, result.trades)
        self._write_csv(equity_csv_path, result.equity_curve)

        return {
            "json": str(json_path),
            "trades_csv": str(trades_csv_path),
            "equity_csv": str(equity_csv_path),
        }

    def to_console(self, result: BacktestResult, paths: dict[str, str] | None = None) -> str:
        metrics = result.metrics
        lines = [
            "Historical Backtest Result",
            f"Symbol: {result.config.symbol}",
            f"Exchange: {result.config.exchange}",
            f"Timeframe: {result.config.timeframe}",
            f"Candles: {result.candles}",
            f"Data source: {result.data_source}",
            f"Signals replayed: {result.signals_seen}",
            f"Trades: {int(metrics['trades'])}",
            f"Winrate: {metrics['winrate']}%",
            f"Profit: {metrics['profit']}",
            f"Max Drawdown: {metrics['max_drawdown']}%",
            f"Sharpe: {metrics['sharpe']}",
            f"Profit Factor: {metrics['profit_factor']}",
            f"Average Win: {metrics['average_win']}",
            f"Average Loss: {metrics['average_loss']}",
            f"Expectancy: {metrics['expectancy']}",
        ]
        if paths:
            lines.extend([
                f"JSON: {paths['json']}",
                f"Trades CSV: {paths['trades_csv']}",
                f"Equity CSV: {paths['equity_csv']}",
            ])
        return "\n".join(lines)

    def _artifact_stem(self, result: BacktestResult) -> str:
        symbol = result.config.symbol.replace("/", "_").replace("-", "_").lower()
        return f"{symbol}_{result.config.exchange}_{result.config.timeframe}_backtest"

    def _write_csv(self, path: Path, rows: list[dict[str, object]]) -> None:
        if not rows:
            path.write_text("", encoding="utf-8")
            return

        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)