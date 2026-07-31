"""Contract tests for the shared entry geometry gate."""

from app.core.models import Candle
from app.decision_agent.models import Decision, EntryPlan
from app.risk.geometry import validate_entry_geometry
from app.risk.risk_agent import RiskAgent
from app.risk.takeprofit import RiskRewardValidator


def test_accepts_valid_long_and_short_at_two_r() -> None:
    long_result = validate_entry_geometry(
        side="BUY", entry=100.0, stop_loss=98.0, take_profit=104.0
    )
    short_result = validate_entry_geometry(
        side="SELL", entry=100.0, stop_loss=102.0, take_profit=96.0
    )
    assert long_result.valid is True
    assert short_result.valid is True
    assert long_result.risk_reward == 2.0
    assert short_result.risk_reward == 2.0


def test_legacy_risk_reward_validator_accepts_decimal_levels_at_exact_two_r() -> None:
    # These production-style decimal levels evaluate microscopically below 2.0
    # in binary floating point even though their mathematical RR is exactly 2R.
    check = RiskRewardValidator(minimum_ratio=2.0).validate_long(
        entry=4.4307,
        stop_loss=4.3376,
        take_profit=4.6169,
    )

    assert check.ratio == 2.0
    assert check.valid is True


def test_rejects_wrong_side_and_low_rr() -> None:
    wrong_side = validate_entry_geometry(
        side="LONG", entry=100.0, stop_loss=101.0, take_profit=104.0
    )
    low_rr = validate_entry_geometry(
        side="SHORT", entry=100.0, stop_loss=102.0, take_profit=97.0
    )
    assert wrong_side.valid is False
    assert "long_sl_not_below_entry" in wrong_side.reasons
    assert low_rr.valid is False
    assert any(reason.startswith("rr_too_low=") for reason in low_rr.reasons)


def test_rejects_stop_outside_percent_bounds() -> None:
    too_tight = validate_entry_geometry(
        side="BUY", entry=100.0, stop_loss=99.9, take_profit=101.0
    )
    too_wide = validate_entry_geometry(
        side="BUY", entry=100.0, stop_loss=90.0, take_profit=120.0
    )
    assert any(reason.startswith("sl_too_tight=") for reason in too_tight.reasons)
    assert any(reason.startswith("sl_too_wide=") for reason in too_wide.reasons)


def test_risk_agent_fail_safe_rejects_invalid_entry_geometry() -> None:
    decision = Decision(
        action="ENTRY_BUY",
        symbol="BTC/USDT",
        confidence="HIGH",
        confidence_score=90.0,
        reasons=["test"],
        entry_plan=EntryPlan(
            side="BUY",
            entry_price=100.0,
            stop_loss=98.0,
            take_profit_1=103.0,
            risk_reward=99.0,  # stale/forged metadata must not bypass geometry.
        ),
        timestamp="2026-01-01T00:00:00Z",
    )
    candles = [
        Candle("BTC/USDT", "2026-01-01T00:00:00Z", 100, 101, 99, 100, 1000)
    ]
    approval = RiskAgent().approve_execution(decision, candles=candles)
    assert approval.approved is False
    assert approval.reason == "invalid_entry_geometry"
    assert approval.checks["entry_geometry"]["risk_reward"] == 1.5