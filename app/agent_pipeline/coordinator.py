"""Coordinator for the deterministic multi-agent trading pipeline.

Entry candidates require empty scanner gates and confidence >= threshold.
Open positions follow a separate monitoring path.

P0 safety:
- Learning is advisory by default (does not change decision scores).
- RiskAgent veto sits between Decision and Executor for ENTRY/EXIT.
- HOLD/SKIP reach Executor as dry-run no-ops when execute is on.
- LLM hooks are read-only explain/audit only.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
from typing import Any

from app.agent_pipeline.models import PipelineResult, ScannerCandidate
from app.chart_agent.agent import ChartReaderAgent
from app.core.models import Candle
from app.decision_agent.agent import DecisionMakerAgent
from app.executor_agent.agent import ExecutorAgent
from app.executor_agent.models import PositionContext
from app.learning_agent.agent import LearningAgent
from app.risk.risk_agent import RiskAgent, RiskApproval


@dataclass(frozen=True)
class AgentPipelineConfig:
    """Coordinator policy. Execution remains disabled by default."""

    min_scanner_confidence: float = 90.0
    execute_decisions: bool = False
    apply_learning_to_decision: bool = False
    require_risk_gate: bool = True
    scanner_chart_conflict_policy: str = "IGNORE"

class AgentPipelineCoordinator:
    """Wires specialist agents without mixing responsibilities."""

    def __init__(
        self,
        *,
        chart_agent: ChartReaderAgent | None = None,
        learning_agent: LearningAgent | None = None,
        decision_agent: DecisionMakerAgent | None = None,
        executor_agent: ExecutorAgent | None = None,
        risk_agent: RiskAgent | None = None,
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
        self.risk_agent = risk_agent or RiskAgent(
            require_risk_gate=self.config.require_risk_gate,
        )
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
        eligible, reason = self._entry_eligible(candidate)
        if not eligible:
            return PipelineResult(
                stage="ENTRY", eligible=False, eligibility_reason=reason,
                chart_reading=None, decision=None, execution=None,
            )
        reading = self.chart_agent.read(candidate.symbol, htf_candles, mtf_candles, ltf_candles)
        reading = self._explain_chart(reading, stage="ENTRY")
        conflict = self._scanner_chart_conflict(candidate.action, reading.bias)
        if conflict and self.config.scanner_chart_conflict_policy == "REJECT":
            return PipelineResult(
                stage="ENTRY", eligible=True,
                eligibility_reason="scanner_chart_conflict_rejected",
                chart_reading=reading, decision=None, execution=None,
                scanner_chart_conflict=conflict,
            )
        insight, learning_advisory = self._load_learning()
        decision = self.decision_agent.decide_entry(reading, insight)
        decision = self._audit_decision(reading, insight, decision, stage="ENTRY")
        self.learning_agent.record_chart_reading(
            reading, stage="ENTRY_CANDIDATE",
            scanner_confidence=candidate.confidence, scanner_gates_passed=True,
            decision=decision.to_dict(),
        )
        risk = self._run_risk_gate(decision, candles=ltf_candles or mtf_candles or htf_candles)
        execution = None
        if self.config.execute_decisions and risk.approved:
            execution = self.executor_agent.execute(decision)
            if execution is not None:
                self._explain_execution(decision, execution)
        elif self.config.execute_decisions and not risk.approved:
            meta = dict(decision.meta)
            meta["risk_rejected"] = risk.to_dict()
            decision = replace(decision, meta=meta)
        return PipelineResult(
            stage="ENTRY", eligible=True,
            eligibility_reason="scanner_gates_passed_and_confidence_qualified",
            chart_reading=reading, decision=decision, execution=execution,
            risk_approval=risk.to_dict(), learning_advisory=learning_advisory,
            scanner_chart_conflict=conflict,
        )

    def monitor_position(self, *, symbol: str, position: PositionContext, htf_candles: list[Candle], mtf_candles: list[Candle], ltf_candles: list[Candle]) -> PipelineResult:
        reading = self.chart_agent.read(symbol, htf_candles, mtf_candles, ltf_candles)
        reading = self._explain_chart(reading, stage="POSITION_MONITOR")
        insight, learning_advisory = self._load_learning()
        decision = self.decision_agent.decide_hold(reading, position.side, insight)
        decision = self._audit_decision(reading, insight, decision, stage="POSITION_MONITOR")
        self.learning_agent.record_chart_reading(reading, stage="POSITION_MONITOR", decision=decision.to_dict())
        risk = self._run_risk_gate(decision, position=position, candles=ltf_candles or mtf_candles or htf_candles)
        execution = None
        if self.config.execute_decisions and risk.approved:
            execution = self.executor_agent.execute(decision, position)
            if execution is not None:
                self._explain_execution(decision, execution)
        elif self.config.execute_decisions and not risk.approved:
            meta = dict(decision.meta); meta["risk_rejected"] = risk.to_dict(); decision = replace(decision, meta=meta)
        return PipelineResult(stage="POSITION_MONITOR", eligible=True, eligibility_reason="open_position_monitoring", chart_reading=reading, decision=decision, execution=execution, risk_approval=risk.to_dict(), learning_advisory=learning_advisory)

    def _entry_eligible(self, candidate: ScannerCandidate) -> tuple[bool, str]:
        if candidate.action not in {"BUY", "SELL"}:
            return False, f"scanner_action={candidate.action}"
        if not candidate.gates_passed:
            return False, "scanner_gates_failed"
        if candidate.confidence < self.config.min_scanner_confidence:
            return False, f"scanner_confidence={candidate.confidence:.1f}<{self.config.min_scanner_confidence:.1f}"
        return True, "qualified"

    def _scanner_chart_conflict(self, scanner_action: str, chart_bias: str) -> str | None:
        if scanner_action == "BUY" and chart_bias == "BEARISH":
            return "scanner_BUY_vs_chart_BEARISH"
        if scanner_action == "SELL" and chart_bias == "BULLISH":
            return "scanner_SELL_vs_chart_BULLISH"
        return None

    def _load_learning(self) -> tuple[Any, dict[str, Any] | None]:
        try:
            raw = self.learning_agent.learn()
            advisory = {
                "total_trades": raw.total_trades,
                "hot_patterns": list(raw.hot_patterns),
                "cold_patterns": list(raw.cold_patterns),
                "worst_regime": raw.worst_regime,
                "min_confluence_recommended": raw.min_confluence_recommended,
                "applied_to_decision": self.config.apply_learning_to_decision,
            }
            if self.config.apply_learning_to_decision:
                return raw, advisory
            return None, advisory
        except Exception as exc:
            return None, {"error": str(exc), "applied_to_decision": False}

    def _run_risk_gate(self, decision, *, position: PositionContext | None = None, candles: list[Candle] | None = None) -> RiskApproval:
        if decision.action in {"SKIP", "HOLD"}:
            return RiskApproval(approved=True, reason=f"noop_allowed={decision.action}", checks={"action": decision.action, "noop": True})
        return self.risk_agent.approve_execution(decision, position=position, candles=candles)

    def _audit_decision(self, reading, insight, decision, *, stage: str):
        if self._decision_llm_client is None or not self._decision_llm_model:
            return decision
        payload = {"stage": stage, "chart_reading": reading.to_dict(), "learning_insight": insight.to_dict() if insight is not None else None, "decision": decision.to_dict(), "instruction": "Audit this deterministic decision. Do not change action. Output JSON only."}
        meta = dict(decision.meta)
        try:
            output = self._decision_llm_client.chat_json(system="You are a read-only decision auditor. Output JSON only.", user=json.dumps(payload, ensure_ascii=False), max_tokens=500, temperature=0.1)
            meta["llm_audit"] = {"enabled": True, "model": self._decision_llm_model, "provider_base_url": self._decision_llm_base_url, "result": output, "final_action_unchanged": True}
            return replace(decision, meta=meta)
        except Exception as exc:
            meta = dict(decision.meta)
            meta["llm_audit"] = {"enabled": True, "model": self._decision_llm_model, "error": str(exc), "fallback": "deterministic_decision_only", "final_action_unchanged": True}
            return replace(decision, meta=meta)

    def _explain_chart(self, reading, *, stage: str):
        if self._chart_llm_client is None or not self._chart_llm_model:
            return reading
        payload = {"stage": stage, "chart_reading": reading.to_dict(), "instruction": "Explain chart reading. Do not change bias or levels."}
        meta = dict(reading.meta)
        try:
            output = self._chart_llm_client.chat_json(system="You are a read-only chart explanation assistant. Output JSON only.", user=json.dumps(payload, ensure_ascii=False), max_tokens=600, temperature=0.2)
            meta["llm_explanation"] = {"enabled": True, "model": self._chart_llm_model, "provider_base_url": self._chart_llm_base_url, "result": output, "deterministic_fields_unchanged": True}
        except Exception as exc:
            meta["llm_explanation"] = {"enabled": True, "model": self._chart_llm_model, "error": str(exc), "fallback": "deterministic_chart_only", "deterministic_fields_unchanged": True}
        return replace(reading, meta=meta)

    def _explain_execution(self, decision, execution) -> None:
        if self._executor_llm_client is None or not self._executor_llm_model:
            return
        payload = {"decision": decision.to_dict(), "execution": execution.to_dict(), "instruction": "Explain execution report. Do not change orders."}
        meta = dict(execution.plan.meta)
        try:
            output = self._executor_llm_client.chat_json(system="You are a read-only executor report explainer. Output JSON only.", user=json.dumps(payload, ensure_ascii=False), max_tokens=500, temperature=0.1)
            meta["llm_explanation"] = {"enabled": True, "model": self._executor_llm_model, "provider_base_url": self._executor_llm_base_url, "result": output, "execution_unchanged": True}
        except Exception as exc:
            meta["llm_explanation"] = {"enabled": True, "model": self._executor_llm_model, "error": str(exc), "fallback": "deterministic_execution_only", "execution_unchanged": True}
        execution.plan.meta = meta
