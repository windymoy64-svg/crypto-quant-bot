from __future__ import annotations

import json
from pathlib import Path

from app.research.artifacts import load_research_dataset
from app.research.engine import StrategyResearchEngine
from app.research.runner import generate_strategy_report


def test_strategy_research_generates_required_sections(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    backtests = logs / "backtests"
    backtests.mkdir(parents=True)
    sample = {
        "config": {"symbol": "BTC/USDT", "timeframe": "1h"},
        "trades": [
            {
                "symbol": "BTC/USDT",
                "timeframe": "1h",
                "entry_time": "2026-01-05T10:00:00+00:00",
                "exit_time": "2026-01-05T12:00:00+00:00",
                "net_pnl": 120,
                "gross_pnl": 130,
                "fees": 10,
                "return_percent": 1.2,
                "market_regime": "Bull",
                "rules": [{"rule_id": "trend", "score": 80}],
                "features": [{"feature": "Trend", "score": 60}],
            },
            {
                "symbol": "ETH/USDT",
                "timeframe": "15m",
                "entry_time": "2026-01-06T10:00:00+00:00",
                "exit_time": "2026-01-06T11:00:00+00:00",
                "net_pnl": -40,
                "gross_pnl": -35,
                "fees": 5,
                "return_percent": -0.4,
                "market_regime": "Bear",
                "rules": [{"rule_id": "rsi", "score": 40}],
                "features": [{"feature": "RSI", "score": 30}],
            },
            {
                "symbol": "BTC/USDT",
                "timeframe": "1h",
                "entry_time": "2026-01-07T09:00:00+00:00",
                "exit_time": "2026-01-07T10:00:00+00:00",
                "net_pnl": 50,
                "return_percent": 0.5,
                "market_regime": "Bull",
                "rules": [{"rule_id": "trend", "score": 70}],
            },
        ],
        "equity_curve": [
            {"timestamp": "2026-01-05T00:00:00+00:00", "equity": 10000, "drawdown_percent": 0},
            {"timestamp": "2026-01-06T00:00:00+00:00", "equity": 9960, "drawdown_percent": -0.4},
            {"timestamp": "2026-01-07T00:00:00+00:00", "equity": 10130, "drawdown_percent": 0},
        ],
        "feature_importance": [{"feature": "Momentum", "score": 25}],
    }
    (backtests / "sample.json").write_text(json.dumps(sample), encoding="utf-8")

    dataset = load_research_dataset(logs)
    report = StrategyResearchEngine().analyze(dataset)

    assert report["overall_performance"]["net_profit"] == 130
    assert report["overall_performance"]["gross_profit"] == 170
    assert report["overall_performance"]["gross_loss"] == -40
    assert report["overall_performance"]["win_rate"] == 66.6667
    assert report["pair_analysis"][0]["name"] == "BTC/USDT"
    assert {row["name"] for row in report["timeframe_analysis"]} == {"15m", "1h"}
    assert {row["name"] for row in report["market_regime_analysis"]} == {"Bull", "Bear"}
    assert report["rule_attribution"][0]["rule"] == "trend"
    assert report["longest_winning_streak"] == 1
    assert report["longest_losing_streak"] == 1
    assert report["trade_duration_analysis"]["average_seconds"] == 4800
    assert report["equity_curve_summary"]["points"] == 3


def test_strategy_report_writer_outputs_all_formats(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    backtests = logs / "backtests"
    backtests.mkdir(parents=True)
    (backtests / "empty.json").write_text(json.dumps({"config": {"symbol": "SOL/USDT", "timeframe": "5m"}, "trades": [], "equity_curve": []}), encoding="utf-8")

    paths = generate_strategy_report(logs, tmp_path / "reports")

    assert Path(paths["json"]).exists()
    assert Path(paths["html"]).exists()
    assert Path(paths["csv"]).exists()
    assert "echarts" in Path(paths["html"]).read_text(encoding="utf-8").lower()