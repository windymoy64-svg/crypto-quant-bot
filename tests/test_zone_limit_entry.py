from __future__ import annotations

from app.decision_agent.models import Decision, EntryPlan
from app.executor_agent.agent import ExecutorAgent
from app.paper.realtime_engine import PaperTradingConfig, RealtimePaperTradingEngine


def test_executor_uses_limit_entry_price() -> None:
    decision = Decision(
        action="ENTRY_BUY", symbol="BTC/USDT", confidence="HIGH", confidence_score=90,
        reasons=["fresh"], entry_plan=EntryPlan(
            side="BUY", entry_price=99.0, stop_loss=95.0, take_profit_1=107.0,
            risk_reward=2.0, order_type="LIMIT",
        ), regime="TRENDING_BULLISH", confluence_score=70, timestamp="now",
    )
    report = ExecutorAgent(balance=10_000).execute(decision)
    assert report.plan.orders[0].order_type == "LIMIT"
    assert report.plan.orders[0].price == 99.0


def test_paper_zone_limit_waits_then_fills(tmp_path) -> None:
    engine = RealtimePaperTradingEngine(PaperTradingConfig(
        enabled=True, starting_balance=10_000, risk_percent=1, max_open_positions=3,
        state_path=str(tmp_path / "state.json"), trades_path=str(tmp_path / "trades.jsonl"),
    ))
    signal = {
        "symbol": "BTC/USDT", "action": "BUY", "entry": 95.0,
        "current_price": 100.0, "entry_zone": [94.0, 96.0], "entry_mode": "LIMIT",
        "zone_limit": True, "expires_in_seconds": 600, "stop_loss": 92.0,
        "take_profit": [102.5], "confidence": 90.0,
    }
    waiting = engine.process_signals([signal])
    assert not waiting["open_positions"]
    assert waiting["pending_orders"]

    signal["current_price"] = 95.5
    filled = engine.process_signals([signal])
    assert filled["open_positions"][0]["entry"] == 95.0
    assert any(event["reason"] == "limit_price_reached" for event in filled["events"])
