"""Coordinator for the deterministic multi-agent trading pipeline.

Entry candidates are deliberately restricted to scanner candidates whose gate
list is empty and confidence is at least 90. Open positions follow a separate
monitoring path and are always read by the Chart Agent.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.chart_agent.agent import ChartReaderAgent
from app.core.models import Candle
from app.decision_agent.agent import DecisionMakerAgent
from app.executor_agent.agent import ExecutorAgent
from app.executor_agent.models import PositionContext
from app.learning_agent.agent import LearningAgent
from app.agent_pipeline.models import PipelineResult, ScannerCandidate


@dataclass(frozen=True)
class AgentPipelineConfig:
    """Coordinator policy. Execution remains disabled by default."""

    min_scanner_confidence: float = 90.0
    execute_decisions: bool = False


class AgentPipelineCoordinator:
    """Wires the four specialist agents without mixing responsibilities."""

    def __init__(
        self,
        *,
        chart_agent: ChartReaderAgent | None = None,
        learning_agent: LearningAgent | None = None,
        decision_agent: DecisionMakerAgent | None = None,
        executor_agent: ExecutorAgent | None = None,
        config: AgentPipelineConfig | None = None,
    ) -> None:
        self.chart_agent = chart_agent or ChartReaderAgent()
        self.learning_agent = learning_agent or LearningAgent()
        self.decision_agent = decision_agent or DecisionMakerAgent()
        self.executor_agent = executor_agent or ExecutorAgent()
        self.config = config or AgentPipelineConfig()

    def process_entry_candidate(
        self,
        candidate: ScannerCandidate,
        *,
        htf_candles: list[Candle],
        mtf_candles: list[Candle],
        ltf_candles: list[Candle],
    ) -> PipelineResult:
        """Filter an entry only after scanner gates pass and confidence >= 90."""
        eligible, reason = self._entry_eligible(candidate)
        if not eligible:
            return PipelineResult(
                stage="ENTRY",
                eligible=False,
                eligibility_reason=reason,
                chart_reading=None,
                decision=None,
                execution=None,
            )

        reading = self.chart_agent.read(
            candidate.symbol, htf_candles, mtf_candles, ltf_candles
        )
        insight = self.learning_agent.learn()
        decision = self.decision_agent.decide_entry(reading, insight)
        self.learning_agent.record_chart_reading(
            reading,
            stage="ENTRY_CANDIDATE",
            scanner_confidence=candidate.confidence,
            scanner_gates_passed=True,
            decision=decision.to_dict(),
        )

        execution = (
            self.executor_agent.execute(decision)
            if self.config.execute_decisions
            else None
        )
        return PipelineResult(
            stage="ENTRY",
            eligible=True,
            eligibility_reason="scanner_gates_passed_and_confidence_qualified",
            chart_reading=reading,
            decision=decision,
            execution=execution,
        )

    def monitor_position(
        self,
        *,
        symbol: str,
        position: PositionContext,
        htf_candles: list[Candle],
        mtf_candles: list[Candle],
        ltf_candles: list[Candle],
    ) -> PipelineResult:
        """Read every open position and decide HOLD/EXIT independently of scan gates."""
        reading = self.chart_agent.read(symbol, htf_candles, mtf_candles, ltf_candles)
        insight = self.learning_agent.learn()
        decision = self.decision_agent.decide_hold(reading, position.side, insight)
        self.learning_agent.record_chart_reading(
            reading,
            stage="POSITION_MONITOR",
            decision=decision.to_dict(),
        )
        execution = (
            self.executor_agent.execute(decision, position)
            if self.config.execute_decisions and decision.action == "EXIT"
            else None
        )
        return PipelineResult(
            stage="POSITION_MONITOR",
            eligible=True,
            eligibility_reason="open_position_monitoring",
            chart_reading=reading,
            decision=decision,
            execution=execution,
        )

    def _entry_eligible(self, candidate: ScannerCandidate) -> tuple[bool, str]:
        if candidate.action not in {"BUY", "SELL"}:
            return False, f"scanner_action={candidate.action}"
        if not candidate.gates_passed:
            return False, "scanner_gates_failed"
        if candidate.confidence < self.config.min_scanner_confidence:
            return False, (
                f"scanner_confidence={candidate.confidence:.1f}"
                f"<{self.config.min_scanner_confidence:.1f}"
            )
        return True, "qualified"