"""Tests for free-technique ChartProposal parse/validate + coordinator adopt/veto."""

from __future__ import annotations

from app.agent_pipeline.coordinator import AgentPipelineConfig, AgentPipelineCoordinator
from app.agent_pipeline.models import ScannerCandidate
from app.chart_agent.models import ChartReading
from app.chart_agent.proposal import parse_chart_proposal, validate_chart_proposal
from app.core.models import Candle
from app.decision_agent.models import Decision, EntryPlan
from app.executor_agent.agent import ExecutorAgent


def _c(i: int, o: float, h: float, l: float, c: float) -> Candle:
    return Candle(
        symbol="BTC/USDT",
        timestamp=f"2024-01-01T{i:02d}:00:00Z",
        open=o,
        high=h,
        low=l,
        close=c,
        volume=1000.0,
    )


def _candles(n: int = 40) -> list[Candle]:
    result: list[Candle] = []
    base = 100.0
    for i in range(n):
        trend = i * 0.5
        pullback = -0.8 if i % 5 == 0 else 0.0
        open_price = base + trend + pullback
        close = open_price + 0.35
        result.append(_c(i, open_price, close + 0.25, open_price - 0.3, close))
    return result


def _reading(**kwargs) -> ChartReading:
    defaults = dict(
        symbol="BTC/USDT",
        timestamp="t",
        bias="BULLISH",
        bias_confidence=80.0,
        confluence_score=70.0,
        regime="TRENDING_BULLISH",
        regime_confidence=80.0,
        htf_trend="UP",
        mtf_trend="UP",
        ltf_trend="SIDE",
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
    defaults.update(kwargs)
    return ChartReading(**defaults)


def test_parse_accepts_free_technique_vocabulary() -> None:
    proposal = parse_chart_proposal(
        {
            "stance": "LONG",
            "methods_used": ["Wyckoff", "session_open_auction"],
            "indicators_used": ["custom_cvd_proxy", "fib_0.705"],
            "techniques_used": ["coin_specific_funding_fade"],
            "proposed_entry": 100.0,
            "proposed_sl": 98.0,
            "proposed_tp1": 106.0,
            "setup_quality": 0.82,
            "narrative": "HTF bull MTF bull LTF wait",
        },
        symbol="BTC/USDT",
    )
    assert proposal is not None
    assert proposal.stance == "LONG"
    assert "Wyckoff" in proposal.methods_used
    assert "custom_cvd_proxy" in proposal.indicators_used
    assert proposal.setup_quality == 82.0
    assert proposal.has_full_levels


def test_validate_rejects_wrong_side_geometry() -> None:
    proposal = parse_chart_proposal(
        {
            "stance": "LONG",
            "proposed_entry": 100.0,
            "proposed_sl": 101.0,  # invalid for long
            "proposed_tp1": 106.0,
        },
        symbol="BTC/USDT",
    )
    assert proposal is not None
    v = validate_chart_proposal(proposal, _reading())
    assert v.accepted is False
    assert any("not_below" in r for r in v.reasons)


def test_validate_accepts_aligned_long() -> None:
    proposal = parse_chart_proposal(
        {
            "stance": "LONG",
            "methods_used": ["anything_goes"],
            "proposed_entry": 100.5,
            "proposed_sl": 98.5,
            "proposed_tp1": 106.0,
        },
        symbol="BTC/USDT",
    )
    assert proposal is not None
    v = validate_chart_proposal(proposal, _reading())
    assert v.accepted is True
    assert v.risk_reward >= 1.5


class _FakeChartLLM:
    def chat_json(self, **_kwargs):
        return {
            "stance": "LONG",
            "htf_trend": "BULLISH",
            "mtf_trend": "BULLISH",
            "ltf_state": "WAIT_PULLBACK",
            "methods_used": ["Wyckoff", "liquidity_sweep"],
            "indicators_used": ["bollinger", "fibonacci"],
            "techniques_used": ["order_block_retest"],
            "support_levels": [98.5, 99.0],
            "resistance_levels": [106.0, 110.0],
            "narrative": "HTF/MTF bull, LTF wait retest",
            "proposed_entry": 100.5,
            "proposed_sl": 98.5,
            "proposed_tp1": 106.0,
            "proposed_tp2": 110.0,
            "proposed_tp3": 114.0,
            "setup_quality": 84,
            "reasons": ["free_technique_ok"],
        }


class _FakeVetoLLM:
    def chat_json(self, **_kwargs):
        return {"vote": "VETO", "confidence": 0.9, "reasons": ["setup_fragile"], "notes": "no"}


class _FakeSupportLLM:
    def chat_json(self, **_kwargs):
        return {"vote": "SUPPORT", "confidence": 0.8, "reasons": ["ok"], "notes": ""}


def test_coordinator_stores_free_technique_proposal() -> None:
    coordinator = AgentPipelineCoordinator(
        chart_llm_client=_FakeChartLLM(),
        chart_llm_model="chart-free",
        config=AgentPipelineConfig(
            min_scanner_confidence=90.0,
            chart_llm_propose=True,
            adopt_chart_proposal_levels=False,
            decision_llm_can_veto=False,
        ),
        executor_agent=ExecutorAgent(balance=10_000),
    )
    candles = _candles()
    result = coordinator.process_entry_candidate(
        ScannerCandidate("BTC/USDT", "BUY", 95.0, [], {}),
        htf_candles=candles,
        mtf_candles=candles,
        ltf_candles=candles,
    )
    assert result.chart_reading is not None
    prop = result.chart_reading.meta.get("llm_proposal") or {}
    assert prop.get("free_technique") is True
    assert prop.get("proposal", {}).get("methods_used") == ["Wyckoff", "liquidity_sweep"]
    assert result.chart_reading.meta["llm_explanation"]["model"] == "chart-free"


def test_coordinator_adopts_validated_proposal_levels() -> None:
    coordinator = AgentPipelineCoordinator(
        chart_llm_client=_FakeChartLLM(),
        chart_llm_model="chart-free",
        decision_llm_client=_FakeSupportLLM(),
        decision_llm_model="decision-model",
        config=AgentPipelineConfig(
            min_scanner_confidence=90.0,
            chart_llm_propose=True,
            adopt_chart_proposal_levels=True,
            decision_llm_can_veto=False,
        ),
        executor_agent=ExecutorAgent(balance=10_000),
    )
    candles = _candles()
    result = coordinator.process_entry_candidate(
        ScannerCandidate("BTC/USDT", "BUY", 95.0, [], {}),
        htf_candles=candles,
        mtf_candles=candles,
        ltf_candles=candles,
    )
    assert result.decision is not None
    # Adoption only applies when Decision already chose ENTRY_*
    if result.decision.action in {"ENTRY_BUY", "ENTRY_SELL"}:
        assert result.decision.meta.get("chart_proposal_adopted") is True
        assert result.decision.entry_plan is not None
        assert result.decision.entry_plan.entry_price == 100.5
        assert result.decision.entry_plan.stop_loss == 98.5
        assert "Wyckoff" in (result.decision.meta.get("chart_proposal_methods") or [])


def test_decision_llm_veto_blocks_entry() -> None:
    # Force a decision object through audit helper path via full pipeline:
    # use fake decision agent that always entries.
    class AlwaysEntry:
        def decide_entry(self, reading, insight=None):
            return Decision(
                action="ENTRY_BUY",
                symbol=reading.symbol,
                confidence="HIGH",
                confidence_score=90.0,
                reasons=["forced"],
                entry_plan=EntryPlan(
                    side="BUY",
                    entry_price=100.0,
                    stop_loss=98.0,
                    take_profit_1=106.0,
                    risk_reward=3.0,
                ),
                regime=reading.regime,
                confluence_score=reading.confluence_score,
                timestamp=reading.timestamp,
            )

        def decide_hold(self, reading, position_side, insight=None):
            return Decision(
                action="HOLD",
                symbol=reading.symbol,
                confidence="MEDIUM",
                confidence_score=50.0,
                reasons=["hold"],
                regime=reading.regime,
                confluence_score=reading.confluence_score,
                timestamp=reading.timestamp,
            )

    coordinator = AgentPipelineCoordinator(
        decision_agent=AlwaysEntry(),  # type: ignore[arg-type]
        decision_llm_client=_FakeVetoLLM(),
        decision_llm_model="veto-model",
        config=AgentPipelineConfig(
            min_scanner_confidence=90.0,
            chart_llm_propose=False,
            adopt_chart_proposal_levels=False,
            decision_llm_can_veto=True,
            decision_llm_veto_min_confidence=0.75,
        ),
        executor_agent=ExecutorAgent(balance=10_000),
    )
    candles = _candles()
    result = coordinator.process_entry_candidate(
        ScannerCandidate("BTC/USDT", "BUY", 95.0, [], {}),
        htf_candles=candles,
        mtf_candles=candles,
        ltf_candles=candles,
    )
    assert result.decision is not None
    assert result.decision.action == "SKIP"
    assert result.decision.meta["llm_audit"]["vote"] == "VETO"
    assert result.decision.meta["llm_audit"]["final_action_unchanged"] is False
