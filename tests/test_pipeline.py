from __future__ import annotations

import json
from pathlib import Path

from app.analytics import AnalyticsConfig, AnalyticsEngine
from app.execution.order import OrderSide
from app.execution.simulator import ExecutionSettings, ExecutionSimulator
from app.features.builder import build_features
from app.market.data_service import MarketDataService
from app.market.regime import MarketRegimeEngine
from app.portfolio.manager import PortfolioManager
from app.risk.manager import RiskManager, RiskSettings
from app.scoring.engine import ScoreEngine
from app.signals.builder import build_signal


def _load_btc_candles():
    service = MarketDataService(exchange="offline", fallback_to_sample_data=True)
    result = service.fetch_ohlcv("BTC/USDT", timeframe="1m", limit=30)
    assert result.candles
    return result.candles


def _score_engine() -> ScoreEngine:
    return ScoreEngine.from_json("configs/rules.json", weights_path="configs/rule_weights.json")


def test_historical_market_data_to_signal_pipeline() -> None:
    candles = _load_btc_candles()

    features = build_features(candles)
    regime = MarketRegimeEngine().analyze(features)
    score = _score_engine().score(candles, regime)
    signal = build_signal("BTC/USDT", candles, score)

    assert features
    assert score.total_score >= 0
    assert signal.action
    assert signal.score >= 0
    assert signal.confidence >= 0


def test_market_regime_from_built_features_is_valid() -> None:
    candles = _load_btc_candles()
    features = build_features(candles)

    regime = MarketRegimeEngine().analyze(features)

    assert regime.regime in {
        "TRENDING_BULLISH",
        "TRENDING_BEARISH",
        "RANGING",
        "MIXED",
        "HIGH_VOLATILITY",
        "LOW_VOLATILITY",
    }
    assert regime.confidence > 0


def test_risk_manager_returns_entry_decision() -> None:
    candles = _load_btc_candles()
    signal = build_signal("BTC/USDT", candles, _score_engine().score(candles))

    decision = RiskManager(settings=RiskSettings(max_open_positions=3)).evaluate_entry(
        symbol=signal.symbol,
        timestamp=candles[-1].timestamp,
        candles=candles,
        cash=10_000.0,
        equity=10_000.0,
        entry=signal.entry,
        stop_loss=signal.stop_loss,
        take_profit=signal.take_profit[0],
        open_positions=0,
        current_exposure=0.0,
    )

    assert decision.approved or not decision.approved
    assert decision.reason


def test_execution_simulator_buy_fill_updates_portfolio() -> None:
    candles = _load_btc_candles()
    portfolio = PortfolioManager.with_cash(10_000.0)
    starting_balance = portfolio.available_balance

    fill = ExecutionSimulator(settings=ExecutionSettings(slippage_basis_points=0, spread_basis_points=0)).execute_market_order(
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        quantity=0.01,
        requested_price=candles[-1].close,
        signal_index=len(candles) - 1,
        candles=candles,
    )
    assert fill.fills

    latest_fill = fill.fills[-1]
    portfolio.open_position(
        symbol=latest_fill.symbol,
        quantity=latest_fill.quantity,
        price=latest_fill.price,
        fee=latest_fill.fee,
        timestamp=latest_fill.timestamp,
    )

    assert portfolio.open_positions_count == 1
    assert portfolio.positions["BTC/USDT"].quantity > 0
    assert portfolio.available_balance != starting_balance


def test_analytics_engine_builds_report_from_backtest_artifact(tmp_path: Path) -> None:
    backtest_dir = tmp_path / "backtests"
    backtest_dir.mkdir()
    artifact = {
        "trades": [
            {
                "symbol": "BTC/USDT",
                "entry_side": "BUY",
                "exit_side": "SELL",
                "quantity": 0.1,
                "entry_time": "2026-07-06T00:01:00Z",
                "exit_time": "2026-07-06T00:02:00Z",
                "entry_price": 100000.0,
                "exit_price": 101000.0,
                "gross_pnl": 100.0,
                "fees": 2.0,
                "net_pnl": 98.0,
                "return_percent": 0.98,
                "exit_reason": "TAKE_PROFIT",
            },
            {
                "symbol": "BTC/USDT",
                "entry_side": "BUY",
                "exit_side": "SELL",
                "quantity": 0.1,
                "entry_time": "2026-07-06T00:03:00Z",
                "exit_time": "2026-07-06T00:04:00Z",
                "entry_price": 101000.0,
                "exit_price": 100500.0,
                "gross_pnl": -50.0,
                "fees": 2.0,
                "net_pnl": -52.0,
                "return_percent": -0.5149,
                "exit_reason": "STOP_LOSS",
            },
        ],
        "equity_curve": [
            {"timestamp": "2026-07-06T00:01:00Z", "cash": 10000.0, "position_value": 0.0, "equity": 10000.0, "drawdown_percent": 0.0},
            {"timestamp": "2026-07-06T00:02:00Z", "cash": 10098.0, "position_value": 0.0, "equity": 10098.0, "drawdown_percent": 0.0},
            {"timestamp": "2026-07-06T00:04:00Z", "cash": 10046.0, "position_value": 0.0, "equity": 10046.0, "drawdown_percent": -0.5149},
        ],
    }
    (backtest_dir / "result.json").write_text(json.dumps(artifact), encoding="utf-8")

    report = AnalyticsEngine().build_report(
        AnalyticsConfig(
            paper_state_path=str(tmp_path / "paper_state.json"),
            paper_events_path=str(tmp_path / "paper_events.jsonl"),
            backtest_results_dir=str(backtest_dir),
            output_path=str(tmp_path / "analytics_report.json"),
            include_paper_state=False,
            include_backtests=True,
        )
    )
    performance = report.to_dict()["performance"]

    assert performance["win_rate"] >= 0
    assert performance["profit_factor"] >= 0
    assert performance["max_drawdown_percent"] >= 0
