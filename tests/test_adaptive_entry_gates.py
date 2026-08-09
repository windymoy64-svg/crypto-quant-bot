from __future__ import annotations

from dataclasses import dataclass

from app.agent_pipeline.coordinator import AgentPipelineConfig, AgentPipelineCoordinator
from app.agent_pipeline.models import ScannerCandidate
from app.chart_agent.models import ChartReading
from app.core.models import Candle


def _reading(**overrides) -> ChartReading:
    values = dict(
        symbol="BTC/USDT", timestamp="now", bias="BULLISH", bias_confidence=80.0,
        confluence_score=70.0, regime="TRENDING_BULLISH", regime_confidence=80.0,
        htf_trend="BULLISH", mtf_trend="BULLISH", ltf_trend="BULLISH",
        trends_aligned=True, candle_patterns=[], structure_breaks=[], order_blocks=[],
        key_levels=[], technique_signals=[], narrative="", reasons=[], suggested_bias="BULLISH",
        entry_zone=(99.0, 101.0), invalidation_level=97.0,
        momentum_phase={"phase": "fresh", "volume_ratio": 1.5},
    )
    values.update(overrides)
    return ChartReading(**values)


@dataclass
class _Chart:
    reading: ChartReading

    def read(self, *_args):
        return self.reading


def test_timing_gate_rejects_extended_momentum() -> None:
    coordinator = AgentPipelineCoordinator(
        chart_agent=_Chart(_reading(momentum_phase={"phase": "extended", "volume_ratio": 2.0})),
        config=AgentPipelineConfig(entry_timing_enabled=True, require_fresh_break=True),
    )
    result = coordinator.process_entry_candidate(
        ScannerCandidate("BTC/USDT", "BUY", 95.0, [], {}),
        htf_candles=[], mtf_candles=[], ltf_candles=[],
    )
    assert result.eligibility_reason == "momentum_not_fresh"
    assert result.decision is None


def test_timing_gate_rejects_misaligned_trend() -> None:
    coordinator = AgentPipelineCoordinator(
        chart_agent=_Chart(_reading(trends_aligned=False)),
        config=AgentPipelineConfig(entry_timing_enabled=True, hard_trend_alignment=True),
    )
    result = coordinator.process_entry_candidate(
        ScannerCandidate("BTC/USDT", "BUY", 95.0, [], {}),
        htf_candles=[], mtf_candles=[], ltf_candles=[],
    )
    assert result.eligibility_reason == "trends_not_aligned_blocked"
