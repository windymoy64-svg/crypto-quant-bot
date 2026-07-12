from pathlib import Path

from app.paper.realtime_engine import PaperTradingConfig, RealtimePaperTradingEngine


def test_paper_engine_opens_virtual_position(tmp_path: Path) -> None:
    config = PaperTradingConfig(
        enabled=True,
        starting_balance=10_000,
        risk_percent=1,
        max_open_positions=3,
        state_path=str(tmp_path / "paper_state.json"),
        trades_path=str(tmp_path / "paper_trades.jsonl"),
    )
    engine = RealtimePaperTradingEngine(config)
    signal = {
        "symbol": "BTC/USDT",
        "action": "BUY",
        "entry": 100.0,
        "stop_loss": 95.0,
        "take_profit": [110.0],
        "confidence": 95.0,
    }

    result = engine.process_signals([signal])

    assert result["open_positions"]
    assert result["events"][0]["type"] == "opened"


def test_paper_engine_closes_position_on_take_profit(tmp_path: Path) -> None:
    config = PaperTradingConfig(
        enabled=True,
        starting_balance=10_000,
        risk_percent=1,
        max_open_positions=3,
        state_path=str(tmp_path / "paper_state.json"),
        trades_path=str(tmp_path / "paper_trades.jsonl"),
    )
    engine = RealtimePaperTradingEngine(config)
    engine.process_signals(
        [
            {
                "symbol": "BTC/USDT",
                "action": "BUY",
                "entry": 100.0,
                "stop_loss": 95.0,
                "take_profit": [110.0],
                "confidence": 95.0,
            }
        ]
    )

    result = engine.process_signals(
        [
            {
                "symbol": "BTC/USDT",
                "action": "SKIP",
                "entry": 111.0,
                "stop_loss": 95.0,
                "take_profit": [120.0],
                "confidence": 70.0,
            }
        ]
    )

    assert not result["open_positions"]
    assert result["events"][0]["type"] == "closed"


def test_paper_engine_updates_unranked_position_with_tracking_tick(
    tmp_path: Path,
) -> None:
    config = PaperTradingConfig(
        enabled=True,
        starting_balance=10_000,
        risk_percent=1,
        max_open_positions=3,
        state_path=str(tmp_path / "paper_state.json"),
        trades_path=str(tmp_path / "paper_trades.jsonl"),
    )
    engine = RealtimePaperTradingEngine(config)
    engine.process_signals(
        [
            {
                "symbol": "ALLO/USDT",
                "action": "BUY",
                "entry": 0.37,
                "stop_loss": 0.36,
                "take_profit": [0.40, 0.42, 0.44],
                "confidence": 95.0,
            }
        ]
    )

    result = engine.process_signals(
        [
            {
                "symbol": "ALLO/USDT",
                "action": "SKIP",
                "entry": 0.375,
                "stop_loss": 0.36,
                "take_profit": [0.40, 0.42, 0.44],
                "confidence": 0.0,
            }
        ]
    )

    position = result["open_positions"][0]
    assert position["last_price"] == 0.375
    assert position["unrealized_pnl"] > 0
