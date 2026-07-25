"""Tests for Learning Journal Coach PolicyPatch (parse/validate + Decision hook)."""

from __future__ import annotations

from app.chart_agent.models import ChartReading
from app.decision_agent.agent import DecisionMakerAgent
from app.learning_agent.policy import parse_policy_patch, validate_policy_patch


def _reading(regime: str = "TRENDING_BULLISH", confluence: float = 70.0) -> ChartReading:
    return ChartReading(
        symbol="BTC/USDT",
        timestamp="t",
        bias="BULLISH",
        bias_confidence=85.0,
        confluence_score=confluence,
        regime=regime,
        regime_confidence=80.0,
        htf_trend="UP",
        mtf_trend="UP",
        ltf_trend="UP",
        trends_aligned=True,
        candle_patterns=[],
        structure_breaks=[],
        order_blocks=[],
        key_levels=[],
        technique_signals=[],
        narrative="",
        reasons=[],
        suggested_bias="BULLISH",
        entry_zone=(100.0, 101.0),
        invalidation_level=98.5,
        meta={},
    )


def test_parse_clamps_out_of_range_fields() -> None:
    patch = parse_policy_patch(
        {
            "policy_patch": {
                "min_confluence_delta": 999,
                "size_multiplier": 0.01,
                "block_regimes": ["RANGING", "NOT_A_REGIME"],
                "confidence": 5,
                "requires_min_samples": 30,
            }
        }
    )
    assert patch is not None
    assert patch.min_confluence_delta == 15.0  # clamped
    assert patch.size_multiplier == 0.5  # clamped
    assert patch.block_regimes == ["RANGING"]  # unknown dropped
    assert patch.confidence == 0.05  # 5 > 1 -> /100 -> 0.05, within [0,1]


def test_validate_shadow_vs_apply() -> None:
    patch = parse_policy_patch(
        {
            "policy_patch": {
                "block_regimes": ["HIGH_VOLATILITY"],
                "confidence": 0.9,
                "requires_min_samples": 30,
            }
        }
    )
    assert patch is not None
    # insufficient samples -> not accepted
    v_low = validate_policy_patch(patch, total_trades=10, apply_enabled=True)
    assert v_low.accepted is False
    # enough samples, shadow -> accepted but not applied
    v_shadow = validate_policy_patch(patch, total_trades=50, apply_enabled=False)
    assert v_shadow.accepted is True
    assert v_shadow.applied is False
    # enough samples, apply on -> applied
    v_apply = validate_policy_patch(patch, total_trades=50, apply_enabled=True)
    assert v_apply.applied is True


def test_decision_respects_block_regime_when_policy_applied() -> None:
    agent = DecisionMakerAgent()
    patch = parse_policy_patch(
        {
            "policy_patch": {
                "block_regimes": ["TRENDING_BULLISH"],
                "confidence": 0.9,
                "requires_min_samples": 0,
            }
        }
    )
    reading = _reading(regime="TRENDING_BULLISH")
    decision = agent.decide_entry(reading, None, policy=patch)
    assert decision.action == "SKIP"
    assert any("policy_block_regime" in r for r in decision.reasons)


def test_decision_without_policy_is_unchanged_path() -> None:
    agent = DecisionMakerAgent()
    reading = _reading(regime="TRENDING_BULLISH")
    d_none = agent.decide_entry(reading, None)
    d_policy_none = agent.decide_entry(reading, None, policy=None)
    assert d_none.action == d_policy_none.action
