"""Tests for Executor Agent."""

from __future__ import annotations

from app.decision_agent.models import Decision, EntryPlan, ExitPlan
from app.executor_agent.agent import ExecutorAgent
from app.executor_agent.models import PositionContext


def _entry_decision(action: str = "ENTRY_BUY") -> Decision:
    return Decision(
        action=action,
        symbol="BTC/USDT",
        confidence="HIGH",
        confidence_score=85.0,
        reasons=["test"],
        entry_plan=EntryPlan(
            side="BUY" if action == "ENTRY_BUY" else "SELL",
            entry_price=100.0,
            stop_loss=97.0,
            take_profit_1=106.0,
            take_profit_2=109.0,
            take_profit_3=112.0,
            risk_reward=2.0,
        ),
        regime="TRENDING_BULLISH",
        confluence_score=80.0,
        timestamp="2024-01-01T10:00:00Z",
    )


def test_execute_entry_dry_run() -> None:
    agent = ExecutorAgent(balance=10_000.0, risk_percent=1.0)
    report = agent.execute(_entry_decision())

    assert report.success is True
    assert report.plan.dry_run is True
    assert len(report.results) >= 3  # entry + SL + at least 1 TP
    assert report.total_filled_quantity > 0
    assert report.average_entry_price == 100.0
    assert report.results[0].status == "FILLED"
    assert all(result.status == "SUBMITTED" for result in report.results[1:])


def test_execute_entry_sell() -> None:
    agent = ExecutorAgent(balance=10_000.0)
    report = agent.execute(_entry_decision("ENTRY_SELL"))

    assert report.success is True
    entry_order = report.plan.orders[0]
    assert entry_order.side == "SELL"
    sl_order = report.plan.orders[1]
    assert sl_order.side == "BUY"  # SL for short = buy back


def test_execute_skip_noop() -> None:
    agent = ExecutorAgent()
    decision = Decision(
        action="SKIP", symbol="ETH/USDT", confidence="LOW",
        confidence_score=30.0, reasons=["no_bias"],
        regime="MIXED", confluence_score=20.0, timestamp="2024-01-01",
    )
    report = agent.execute(
        decision,
        PositionContext(side="BUY", quantity=2.5, current_price=102.0),
    )
    assert report.success is True
    assert report.total_filled_quantity == 0.0
    assert len(report.results) == 0


def test_execute_hold_noop() -> None:
    agent = ExecutorAgent()
    decision = Decision(
        action="HOLD", symbol="BTC/USDT", confidence="MEDIUM",
        confidence_score=70.0, reasons=["structure_intact"],
        regime="TRENDING_BULLISH", confluence_score=75.0, timestamp="2024-01-01",
    )
    report = agent.execute(
        decision,
        PositionContext(side="BUY", quantity=2.5, current_price=102.0),
    )
    assert report.success is True
    assert len(report.plan.orders) == 0


def test_execute_exit() -> None:
    agent = ExecutorAgent()
    decision = Decision(
        action="EXIT", symbol="BTC/USDT", confidence="HIGH",
        confidence_score=80.0, reasons=["choch_against"],
        exit_plan=ExitPlan(urgency="IMMEDIATE", reason="structure_invalidation"),
        regime="MIXED", confluence_score=30.0, timestamp="2024-01-01",
    )
    report = agent.execute(
        decision,
        PositionContext(side="BUY", quantity=2.5, current_price=102.0),
    )
    assert report.success is True
    assert report.plan.orders[0].order_type == "MARKET"
    assert report.plan.orders[0].reduce_only is True


def test_position_sizing() -> None:
    agent = ExecutorAgent(balance=10_000.0, risk_percent=1.0, leverage=1)
    report = agent.execute(_entry_decision())

    # Risk sizing gives 33.33 units, but max notional is capped at 15%
    # of $10k: $1,500 / $100 = 15 units.
    entry_order = report.plan.orders[0]
    assert entry_order.quantity == 15.0


def test_position_sizing_with_leverage() -> None:
    agent = ExecutorAgent(balance=10_000.0, risk_percent=1.0, leverage=5)
    report = agent.execute(_entry_decision())

    entry_order = report.plan.orders[0]
    # Max leveraged notional: 15% * $10k * 5 = $7,500 => 75 units.
    assert entry_order.quantity == 75.0


def test_exit_requires_position_context() -> None:
    agent = ExecutorAgent()
    decision = Decision(
        action="EXIT", symbol="BTC/USDT", confidence="HIGH",
        confidence_score=80.0, reasons=["invalidation"],
        exit_plan=ExitPlan(urgency="IMMEDIATE", reason="invalidation"),
        regime="MIXED", confluence_score=30.0, timestamp="2024-01-01",
    )
    # No PositionContext supplied — Executor cannot know quantity/side to close.
    report = agent.execute(decision)
    assert report.success is False
    assert "position_context_required" in report.errors


def test_error_no_entry_plan() -> None:
    agent = ExecutorAgent()
    decision = Decision(
        action="ENTRY_BUY", symbol="BTC/USDT", confidence="HIGH",
        confidence_score=90.0, reasons=["test"],
        entry_plan=None,
        regime="TRENDING_BULLISH", confluence_score=80.0, timestamp="2024-01-01",
    )
    report = agent.execute(decision)
    assert report.success is False
    assert "no_entry_plan" in report.errors


def test_live_mode_rejected_without_adapter() -> None:
    agent = ExecutorAgent(live=True, exchange_adapter=None)
    report = agent.execute(_entry_decision())

    # Live mode without adapter → all orders rejected
    assert report.plan.dry_run is False
    for result in report.results:
        assert result.status == "REJECTED"


def test_to_dict() -> None:
    agent = ExecutorAgent()
    report = agent.execute(_entry_decision())
    d = report.to_dict()
    assert isinstance(d, dict)
    assert d["success"] is True
    assert len(d["results"]) >= 3
