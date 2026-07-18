"""Models for the multi-agent coordinator."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

from app.chart_agent.models import ChartReading
from app.decision_agent.models import Decision
from app.executor_agent.models import ExecutionReport


PipelineStage = Literal["ENTRY", "POSITION_MONITOR"]


@dataclass(frozen=True)
class ScannerCandidate:
    """Minimal scanner result accepted by the agent pipeline."""

    symbol: str
    action: Literal["BUY", "SELL", "WATCH", "SKIP"]
    confidence: float
    failed_gates: list[str]
    meta: dict[str, Any]

    @property
    def gates_passed(self) -> bool:
        return not self.failed_gates


@dataclass(frozen=True)
class PipelineResult:
    """Traceable result of one complete agent pipeline invocation."""

    stage: PipelineStage
    eligible: bool
    eligibility_reason: str
    chart_reading: ChartReading | None
    decision: Decision | None
    execution: ExecutionReport | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "eligible": self.eligible,
            "eligibility_reason": self.eligibility_reason,
            "chart_reading": self.chart_reading.to_dict() if self.chart_reading else None,
            "decision": self.decision.to_dict() if self.decision else None,
            "execution": self.execution.to_dict() if self.execution else None,
        }