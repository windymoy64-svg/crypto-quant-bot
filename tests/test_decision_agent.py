"""Tests for Decision Maker Agent."""

from __future__ import annotations

from app.chart_agent.models import (
    BiasDirection,
    ChartReading,
    CandlePatternDetection,
    KeyLevel,
    StructureBreak,
    TechniqueSignal,
)
from app.learning_agent.models import LearningInsight
from app.decision_agent.agent import DecisionMakerAgent


def _reading(
    bias: BiasDirection = "BULLISH",
    confidence: float = 80.0,
    confluence: float = 75.0,
    aligned: bool = True,
    patterns: list[str] | None = None,
    entry_zone: tuple[float, float] | None = (99.0, 101.0),
    invalidation: float | None = 97.0,
    breaks: list[StructureBreak] | None = None,
) -> ChartReading:
    pats = [
        CandlePatternDetection(
            name=p, direction="BULLISH", strength="STRONG",
            candle_count=2, start_index=0, end_index=1,
            reliability=65.0, description="test",
        ) for p in (patterns or [])
    ]
    return ChartReading(
        symbol="BTC/USDT", timestamp="2024-01-01T10:00:00Z",
        bias=bias, bias_confidence=confidence, confluence_score=confluence,
        regime="TRENDING_BULLISH", regime_confidence=70.0,
        htf_trend="UP", mtf_trend="UP", ltf_trend="UP", trends_aligned=aligned,
        candle_patterns=pats, structure_breaks=breaks or [],
        order_blocks=[], key_levels=[
            KeyLevel(price=100.0, kind="support", strength="STRONG", source="test"),
        ],
        technique_signals=[], narrative="test", reasons=["test"],
        suggested_bias=bias, entry_zone=entry_zone,
        invalidation_level=invalidation,
        techniques_used=["acr_plus"], meta={},
    )


def _insight(
    hot: list[str] | None = None,
    cold: list[str] | None = None,
    min_confluence: float = 55.0,
    worst_regime: str = "HIGH_VOLATILITY",
    total: int = 20,
) -> LearningInsight:
    return LearningInsight(
        total_trades=total, overall_winrate=60.0, overall_avg_pnl=1.5,
        overall_profit_factor=1.8, pattern_insights=[], regime_insights=[],
        symbol_insights=[], hot_patterns=hot or [], cold_patterns=cold or [],
        best_regime="TRENDING_BULLISH", worst_regime=worst_regime,
        avg_confluence_winners=78.0, avg_confluence_losers=52.0,
        min_confluence_recommended=min_confluence,
        last_updated="2024-01-01", data_since="2023-01-01",
    )


def test_entry_approved_basic() -> None:
    agent = DecisionMakerAgent()
    decision = agent.decide_entry(_reading())
    assert decision.action == "ENTRY_BUY"
    assert decision.entry_plan is not None
    assert decision.entry_plan.risk_reward >= 2.0


def test_entry_skip_neutral_bias() -> None:
    agent = DecisionMakerAgent()
    decision = agent.decide_entry(_reading(bias="NEUTRAL"))
    assert decision.action == "SKIP"
    assert "no_directional_bias" in decision.reasons


def test_entry_skip_low_confluence() -> None:
    agent = DecisionMakerAgent()
    decision = agent.decide_entry(_reading(confluence=30.0))
    assert decision.action == "SKIP"


def test_entry_hot_pattern_boost() -> None:
    agent = DecisionMakerAgent()
    r = _reading(confidence=68.0, patterns=["morning_star"])
    ins = _insight(hot=["morning_star"])
    decision = agent.decide_entry(r, ins)
    # 68 + 8 (hot boost) = 76 >= 70 threshold
    assert decision.action == "ENTRY_BUY"
    assert decision.learning_boost > 0


def test_entry_cold_pattern_penalty() -> None:
    agent = DecisionMakerAgent()
    r = _reading(confidence=75.0, patterns=["doji"])
    ins = _insight(cold=["doji"])
    decision = agent.decide_entry(r, ins)
    # 75 - 12 (cold) = 63 < 70 threshold → SKIP
    assert decision.action == "SKIP"


def test_hold_intact() -> None:
    agent = DecisionMakerAgent()
    decision = agent.decide_hold(_reading(), "BUY")
    assert decision.action == "HOLD"
    assert "structure_intact" in decision.reasons


def test_hold_exit_on_bias_flip() -> None:
    agent = DecisionMakerAgent()
    decision = agent.decide_hold(_reading(bias="BEARISH", confidence=70.0), "BUY")
    assert decision.action == "EXIT"
    assert decision.exit_plan is not None


def test_hold_exit_on_choch() -> None:
    agent = DecisionMakerAgent()
    brk = StructureBreak(
        break_type="CHoCH", direction="BEARISH", price=98.0,
        index=5, timestamp="2024-01-01T11:00:00Z", swing_origin_index=2,
    )
    decision = agent.decide_hold(_reading(breaks=[brk]), "BUY")
    assert decision.action == "EXIT"
    assert "choch_bearish_against_long" in decision.reasons


def test_hold_exit_low_confluence() -> None:
    agent = DecisionMakerAgent()
    decision = agent.decide_hold(_reading(confluence=30.0), "BUY")
    assert decision.action == "EXIT"


def test_sell_entry() -> None:
    agent = DecisionMakerAgent()
    decision = agent.decide_entry(_reading(bias="BEARISH"))
    assert decision.action == "ENTRY_SELL"


def test_to_dict() -> None:
    agent = DecisionMakerAgent()
    decision = agent.decide_entry(_reading())
    d = decision.to_dict()
    assert isinstance(d, dict)
    assert d["action"] == "ENTRY_BUY"
    assert d["entry_plan"] is not None
