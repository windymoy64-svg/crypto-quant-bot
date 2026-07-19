"""Coordinator for the deterministic multi-agent trading pipeline.

Entry candidates are deliberately restricted to scanner candidates whose gate
list is empty and confidence is at least 90. Open positions follow a separate
monitoring path and are always read by the Chart Agent.
"""

from __future__ import annotations

from dataclasses import replace
from dataclasses import dataclass
import json
from typing import Any

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
        chart_llm_client: Any = None,
        chart_llm_model: str | None = None,
        chart_llm_base_url: str = "",
        decision_llm_client: Any = None,
        decision_llm_model: str | None = None,
        decision_llm_base_url: str = "",
        executor_llm_client: Any = None,
        executor_llm_model: str | None = None,
        executor_llm_base_url: str = "",
    ) -> None:
        self.chart_agent = chart_agent or ChartReaderAgent()
        self.learning_agent = learning_agent or LearningAgent()
        self.decision_agent = decision_agent or DecisionMakerAgent()
        self.executor_agent = executor_agent or ExecutorAgent()
        self.config = config or AgentPipelineConfig()
        self._chart_llm_client = chart_llm_client
        self._chart_llm_model = chart_llm_model
        self._chart_llm_base_url = chart_llm_base_url
        self._decision_llm_client = decision_llm_client
        self._decision_llm_model = decision_llm_model
        self._decision_llm_base_url = decision_llm_base_url
        self._executor_llm_client = executor_llm_client
        self._executor_llm_model = executor_llm_model
        self._executor_llm_base_url = executor_llm_base_url

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
        reading = self._explain_chart(reading, stage="ENTRY")
        insight = self.learning_agent.learn()
        decision = self.decision_agent.decide_entry(reading, insight)
        decision = self._audit_decision(reading, insight, decision, stage="ENTRY")
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
        if execution is not None:
            self._explain_execution(decision, execution)
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
        reading = self._explain_chart(reading, stage="POSITION_MONITOR")
        insight = self.learning_agent.learn()
        decision = self.decision_agent.decide_hold(reading, position.side, insight)
        decision = self._audit_decision(reading, insight, decision, stage="POSITION_MONITOR")
        self.learning_agent.record_chart_reading(
            reading,
            stage="POSITION_MONITOR",
            decision=decision.to_dict(),
        )
        execution = (
            self.executor_agent.execute(decision, position)
            if self.config.execute_decisions
            else None
        )
        if execution is not None:
            self._explain_execution(decision, execution)
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

    def _audit_decision(
        self,
        reading,
        insight,
        decision,
        *,
        stage: str,
    ):
        """Attach optional LLM audit metadata without changing final decision."""
        if self._decision_llm_client is None or not self._decision_llm_model:
            return decision
        payload = {
            "stage": stage,
            "chart_reading": reading.to_dict(),
            "deterministic_learning": insight.to_dict() if insight else None,
            "final_decision": decision.to_dict(),
            "instruction": (
                "Audit consistency only. Do not change action, entry, stop, TP, "
                "quantity, or execution. Return JSON keys: consistent, warnings, explanation."
            ),
        }
        try:
            output = self._decision_llm_client.chat_json(
                system=(
                    "You are a read-only trading decision auditor. The deterministic "
                    "Decision Agent result is final. Audit consistency and explain risks only."
                ),
                user=json.dumps(payload, ensure_ascii=False),
                max_tokens=700,
                temperature=0.1,
            )
            meta = dict(decision.meta)
            meta["llm_audit"] = {
                "enabled": True,
                "model": self._decision_llm_model,
                "provider_base_url": self._decision_llm_base_url,
                "result": output,
                "final_action_unchanged": True,
            }
            return replace(decision, meta=meta)
        except Exception as exc:  # noqa: BLE001 - audit must never block trading logic
            meta = dict(decision.meta)
            meta["llm_audit"] = {
                "enabled": True,
                "model": self._decision_llm_model,
                "error": str(exc),
                "fallback": "deterministic_decision_only",
                "final_action_unchanged": True,
            }
            return replace(decision, meta=meta)

    def _explain_chart(self, reading, *, stage: str):
        """Attach optional LLM chart explanation without changing chart fields."""
        if self._chart_llm_client is None or not self._chart_llm_model:
            return reading
        payload = {
            "stage": stage,
            "chart_reading": reading.to_dict(),
            "instruction": (
                "Explain this deterministic chart reading briefly. Do not change bias, "
                "confluence, entry zone, invalidation, or any trade decision."
            ),
        }
        meta = dict(reading.meta)
        try:
            output = self._chart_llm_client.chat_json(
                system="You are a read-only chart explanation assistant. Output JSON only.",
                user=json.dumps(payload, ensure_ascii=False),
                max_tokens=600,
                temperature=0.2,
            )
            meta["llm_explanation"] = {
                "enabled": True,
                "model": self._chart_llm_model,
                "provider_base_url": self._chart_llm_base_url,
                "result": output,
                "deterministic_fields_unchanged": True,
            }
        except Exception as exc:  # noqa: BLE001
            meta["llm_explanation"] = {
                "enabled": True,
                "model": self._chart_llm_model,
                "error": str(exc),
                "fallback": "deterministic_chart_only",
                "deterministic_fields_unchanged": True,
            }
        return replace(reading, meta=meta)

    def _explain_execution(self, decision, execution) -> None:
        """Attach optional LLM execution explanation to report plan meta only."""
        if self._executor_llm_client is None or not self._executor_llm_model:
            return
        payload = {
            "decision": decision.to_dict(),
            "execution": execution.to_dict(),
            "instruction": (
                "Explain the execution report or rejection. Do not change orders, "
                "quantity, prices, live/dry-run state, or success status."
            ),
        }
        meta = dict(execution.plan.meta)
        try:
            output = self._executor_llm_client.chat_json(
                system="You are a read-only executor report explainer. Output JSON only.",
                user=json.dumps(payload, ensure_ascii=False),
                max_tokens=500,
                temperature=0.1,
            )
            meta["llm_explanation"] = {
                "enabled": True,
                "model": self._executor_llm_model,
                "provider_base_url": self._executor_llm_base_url,
                "result": output,
                "execution_unchanged": True,
            }
        except Exception as exc:  # noqa: BLE001
            meta["llm_explanation"] = {
                "enabled": True,
                "model": self._executor_llm_model,
                "error": str(exc),
                "fallback": "deterministic_execution_only",
                "execution_unchanged": True,
            }
        execution.plan.meta = meta