from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from app.backtest.metrics import calculate_backtest_metrics
from app.backtest.simulator import BacktestSimulator
from app.core.models import Candle
from app.events.events import BacktestFinished
from app.events.publisher import publish
from app.execution.simulator import ExecutionSettings
from app.exchange.public_http_client import PublicHttpExchangeClient
from app.market.history import HistoricalMarketDataEngine
from app.market.sample_data import load_sample_candles
from app.risk.manager import RiskSettings
from app.scoring.engine import ScoreEngine


@dataclass(frozen=True)
class BacktestConfig:
    symbol: str = "BTC/USDT"
    exchange: str = "binance"
    timeframe: str = "1h"
    limit: int = 300
    initial_cash: float = 10_000.0
    position_size_percent: float = 95.0
    fee_rate: float = 0.001
    min_window: int = 30
    rules_path: str = "configs/rules.json"
    weights_path: str | None = None
    maker_fee_rate: float = 0.0002
    taker_fee_rate: float = 0.001
    slippage_basis_points: float = 5.0
    spread_basis_points: float = 2.0
    latency_candles: int = 0
    max_fill_ratio: float = 1.0
    min_fill_ratio: float = 0.25
    risk_per_trade_percent: float = 2.0  # Update dari 1.0% ke 2.0%
    max_exposure_percent: float = 95.0
    max_open_positions: int = 1
    max_daily_drawdown_percent: float = 5.0
    min_risk_reward: float = 2.0  # Update dari 1.2 ke 2.0 (RR 1:2)
    min_atr_percent: float = 0.0
    max_atr_percent: float = 25.0


@dataclass(frozen=True)
class BacktestResult:
    config: BacktestConfig
    data_source: str
    candles: int
    signals_seen: int
    metrics: dict[str, float]
    trades: list[dict[str, object]]
    equity_curve: list[dict[str, object]]
    risk: dict[str, object]
    portfolio: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "config": asdict(self.config),
            "data_source": self.data_source,
            "candles": self.candles,
            "signals_seen": self.signals_seen,
            "metrics": self.metrics,
            "trades": self.trades,
            "equity_curve": self.equity_curve,
            "risk": self.risk,
            "portfolio": self.portfolio,
        }


class HistoricalBacktestEngine:
    def __init__(self, history_engine: HistoricalMarketDataEngine | None = None) -> None:
        self.history_engine = history_engine

    def run(self, config: BacktestConfig) -> BacktestResult:
        history_engine = self.history_engine or HistoricalMarketDataEngine(exchange=config.exchange)
        history = history_engine.load_history(
            config.symbol,
            config.timeframe,
            config.limit,
            lambda symbol, timeframe, limit: self._download_history(config.exchange, symbol, timeframe, limit),
        )
        score_engine = ScoreEngine.from_json(config.rules_path, self._existing_optional_path(config.weights_path))
        simulator = BacktestSimulator(
            initial_cash=config.initial_cash,
            position_size_percent=config.position_size_percent,
            fee_rate=config.fee_rate,
            min_window=config.min_window,
            execution_settings=ExecutionSettings(
                maker_fee_rate=config.maker_fee_rate,
                taker_fee_rate=config.taker_fee_rate,
                slippage_basis_points=config.slippage_basis_points,
                spread_basis_points=config.spread_basis_points,
                latency_candles=config.latency_candles,
                max_fill_ratio=config.max_fill_ratio,
                min_fill_ratio=config.min_fill_ratio,
            ),
            risk_settings=RiskSettings(
                risk_per_trade_percent=config.risk_per_trade_percent,
                max_position_size_percent=config.position_size_percent,
                max_exposure_percent=config.max_exposure_percent,
                max_open_positions=config.max_open_positions,
                max_daily_drawdown_percent=config.max_daily_drawdown_percent,
                min_risk_reward=config.min_risk_reward,
                min_atr_percent=config.min_atr_percent,
                max_atr_percent=config.max_atr_percent,
            ),
        )
        simulation = simulator.run(config.symbol, history.candles, score_engine)
        metrics = calculate_backtest_metrics(simulation.trades, simulation.equity_curve, config.initial_cash)
        publish(
            BacktestFinished(
                symbol=config.symbol,
                timeframe=config.timeframe,
                candles=len(history.candles),
                signals_seen=simulation.signals_seen,
                trades_count=len(simulation.trades),
                metrics=metrics,
                timestamp=history.candles[-1].timestamp if history.candles else "",
            )
        )

        return BacktestResult(
            config=config,
            data_source=history.source,
            candles=len(history.candles),
            signals_seen=simulation.signals_seen,
            metrics=metrics,
            trades=[trade.to_dict() for trade in simulation.trades],
            equity_curve=[point.to_dict() for point in simulation.equity_curve],
            risk=simulation.risk,
            portfolio=simulation.portfolio,
        )

    def _download_history(self, exchange: str, symbol: str, timeframe: str, limit: int) -> list[Candle]:
        try:
            return PublicHttpExchangeClient(exchange).fetch_candles(symbol, timeframe=timeframe, limit=limit)
        except Exception:
            return load_sample_candles(symbol)[-limit:]

    def _existing_optional_path(self, path: str | None) -> str | None:
        if not path:
            return None
        return path if Path(path).exists() else None


def load_backtest_result(path: str | Path) -> dict[str, object]:
    import json

    return json.loads(Path(path).read_text(encoding="utf-8"))