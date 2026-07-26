"""run_backtest tool — guarded offline historical backtest."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.mcp.guards import PROJECT_ROOT, err_payload, ok_payload, resolve_project_path
from app.mcp.tools_backtest import (
    DEFAULT_BACKTEST_DIR,
    _normalize_exchange,
    _normalize_limit,
    _normalize_symbol,
    _normalize_timeframe,
)


def run_backtest(
    symbol: str = "BTC/USDT",
    timeframe: str = "1h",
    limit: int = 300,
    exchange: str = "binance",
    initial_cash: float = 10_000.0,
    use_sample_data: bool = False,
) -> dict[str, Any]:
    """Run a guarded historical backtest; write artifacts to logs/backtests/."""
    try:
        resolved_symbol = _normalize_symbol(symbol)
        resolved_tf = _normalize_timeframe(timeframe)
        resolved_limit = _normalize_limit(limit)
        resolved_exchange = _normalize_exchange(exchange)
        cash = float(initial_cash)
        if cash <= 0 or cash > 1_000_000:
            raise ValueError("initial_cash_out_of_range")

        from app.backtest.engine import BacktestConfig, HistoricalBacktestEngine
        from app.backtest.report import BacktestReporter
        from app.core.models import Candle
        from app.market.history import HistoricalMarketDataEngine, HistoryLoadResult
        from app.market.sample_data import load_sample_candles

        config = BacktestConfig(
            symbol=resolved_symbol,
            exchange=resolved_exchange,
            timeframe=resolved_tf,
            limit=resolved_limit,
            initial_cash=cash,
            rules_path="configs/rules.json",
        )

        engine = HistoricalBacktestEngine()
        if use_sample_data:

            class _SampleOnlyHistory(HistoricalMarketDataEngine):
                def load_history(  # type: ignore[override]
                    self,
                    symbol: str,
                    timeframe: str,
                    limit: int,
                    downloader: Any,
                    force_refresh: bool = False,
                ) -> HistoryLoadResult:
                    candles = load_sample_candles(symbol)[-limit:]
                    if not candles:
                        candles = [
                            Candle(
                                symbol,
                                f"2026-01-01T{i:02d}:00:00Z",
                                100.0 + i,
                                101.0 + i,
                                99.0 + i,
                                100.5 + i,
                                1000.0,
                            )
                            for i in range(min(limit, 80))
                        ]
                    return HistoryLoadResult(
                        symbol=symbol,
                        exchange=self.exchange,
                        timeframe=timeframe,
                        candles=candles,
                        source="sample",
                    )

            engine = HistoricalBacktestEngine(
                history_engine=_SampleOnlyHistory(exchange=resolved_exchange)
            )

        result = engine.run(config)
        out_dir = str(resolve_project_path(DEFAULT_BACKTEST_DIR))
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        paths = BacktestReporter(out_dir).write(result)

        rel_paths: dict[str, str] = {}
        for key, value in paths.items():
            p = Path(value)
            try:
                rel_paths[key] = str(p.resolve().relative_to(PROJECT_ROOT.resolve()))
            except ValueError:
                rel_paths[key] = str(p)

        return ok_payload(
            {
                "available": True,
                "symbol": resolved_symbol,
                "exchange": resolved_exchange,
                "timeframe": resolved_tf,
                "limit": resolved_limit,
                "data_source": result.data_source,
                "candles": result.candles,
                "signals_seen": result.signals_seen,
                "metrics": dict(result.metrics),
                "paths": rel_paths,
                "use_sample_data": bool(use_sample_data),
            }
        )
    except Exception as exc:  # noqa: BLE001
        return err_payload(exc, tool="run_backtest")
