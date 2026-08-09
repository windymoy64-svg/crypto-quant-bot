"""Coordinator for the deterministic multi-agent trading pipeline.

Entry candidates require empty scanner gates and confidence >= threshold.
Open positions follow a separate monitoring path.

P0 safety:
- Learning is advisory by default (does not change decision scores).
- RiskAgent veto sits between Decision and Executor for ENTRY/EXIT.
- HOLD/SKIP reach Executor as dry-run no-ops when execute is on.
- Chart LLM may free-form analyse (any method/indicator) into ChartProposal;
  geometry is validated in Python; proposal is advisory unless adopted.
- Decision LLM audits (optional VETO); never bypasses Risk.
- Executor path remains non-LLM for order placement.
"""


from __future__ import annotations

from dataclasses import dataclass, replace
import json
from typing import Any

from app.agent_pipeline.models import PipelineResult, ScannerCandidate
from app.chart_agent.agent import ChartReaderAgent
from app.chart_agent.proposal import (
    parse_chart_proposal,
    proposal_system_prompt,
    proposal_user_payload,
    validate_chart_proposal,
)
from app.core.models import Candle
from app.decision_agent.agent import DecisionMakerAgent
from app.decision_agent.models import Decision, EntryPlan
from app.executor_agent.agent import ExecutorAgent
from app.executor_agent.models import PositionContext
from app.learning_agent.agent import LearningAgent
from app.learning_agent.policy import parse_policy_patch, validate_policy_patch
from app.risk.risk_agent import RiskAgent, RiskApproval



@dataclass(frozen=True)
class AgentPipelineConfig:
    """Coordinator policy. Execution remains disabled by default."""

    min_scanner_confidence: float = 90.0
    execute_decisions: bool = False
    apply_learning_to_decision: bool = False
    require_risk_gate: bool = True
    scanner_chart_conflict_policy: str = "REJECT"
    # Soft-entry: evaluate top WATCH candidates (chart still must approve ENTRY).
    allow_watch_soft_entry: bool = False
    min_watch_confidence: float = 75.0
    # Chart LLM: free-technique proposal (not fixed indicator set).
    chart_llm_propose: bool = True
    # When True, validated proposal levels may replace EntryPlan on ENTRY_*.
    adopt_chart_proposal_levels: bool = False
    # Decision LLM may VETO entry only; never force ENTRY or veto EXIT.
    decision_llm_can_veto: bool = True
    decision_llm_veto_min_confidence: float = 0.75
    # Learning Journal Coach: LLM PolicyPatch tuning of Decision gates.
    # Shadow by default: computed + logged, but NOT applied to decisions.
    apply_llm_policy: bool = False
    policy_min_confidence: float = 0.6
    entry_timing_enabled: bool = False
    require_fresh_break: bool = False
    require_volume: bool = False
    block_extended_momentum: bool = False
    hard_trend_alignment: bool = False
    block_noise_regimes: bool = False
    allow_zone_limit: bool = False
    limit_expiry_seconds: float = 900.0

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
        reading = self._propose_chart(reading, stage="ENTRY")
        conflict = self._scanner_chart_conflict(candidate.action, reading.bias)
        if conflict and self.config.scanner_chart_conflict_policy == "REJECT":
            return PipelineResult(
                stage="ENTRY", eligible=True,
                eligibility_reason="scanner_chart_conflict_rejected",
                chart_reading=reading, decision=None, execution=None,
                scanner_chart_conflict=conflict,
            )
        timing_reason = self._timing_gate(reading)
        if timing_reason:
            return PipelineResult(
                stage="ENTRY", eligible=True, eligibility_reason=timing_reason,
                chart_reading=reading, decision=None, execution=None,
                scanner_chart_conflict=conflict,
            )
        insight, learning_advisory = self._load_learning()
        policy, policy_validation = self._load_policy(insight)
        # Statistical learning adjustments only when explicitly enabled.
        decision_insight = insight if self.config.apply_learning_to_decision else None
        try:
            decision = self.decision_agent.decide_entry(
                reading, decision_insight, policy=policy
            )
        except TypeError:
            # Backward-compat: decision agents without policy kwarg.
            decision = self.decision_agent.decide_entry(reading, decision_insight)
        decision = self._adopt_chart_proposal(reading, decision)
        decision = self._audit_decision(reading, insight, decision, stage="ENTRY")
        if policy_validation is not None:
            meta = dict(decision.meta)
            meta["policy_patch"] = policy_validation
            decision = replace(decision, meta=meta)
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
            eligibility_reason=reason,
            chart_reading=reading, decision=decision, execution=execution,
            risk_approval=risk.to_dict(), learning_advisory=learning_advisory,
            scanner_chart_conflict=conflict,
        )

    def _timing_gate(self, reading) -> str | None:
        if not self.config.entry_timing_enabled:
            return None
        phase = reading.momentum_phase or {}
        if self.config.require_fresh_break and phase.get("phase") not in {"initial", "fresh"}:
            return "momentum_not_fresh"
        if self.config.block_extended_momentum and phase.get("phase") == "extended":
            return "momentum_extended"
        if self.config.require_volume and float(phase.get("volume_ratio", 0.0)) < 1.15:
            return "momentum_no_volume"
        if self.config.hard_trend_alignment and not reading.trends_aligned:
            return "trends_not_aligned_blocked"
        if self.config.block_noise_regimes and reading.regime in {"RANGING", "MIXED"}:
            return "noise_regime_blocked"
        return None

    def monitor_position(self, *, symbol: str, position: PositionContext, htf_candles: list[Candle], mtf_candles: list[Candle], ltf_candles: list[Candle]) -> PipelineResult:
        reading = self.chart_agent.read(symbol, htf_candles, mtf_candles, ltf_candles)
        # POSITION_MONITOR: skip Chart LLM propose to keep cycle latency safe
        # (9+ open positions * multi-second LLM calls stalls realtime). Entry path
        # still uses free-technique proposal. Decision audit remains available.
        insight, learning_advisory = self._load_learning()
        decision_insight = insight if self.config.apply_learning_to_decision else None
        decision = self.decision_agent.decide_hold(reading, position.side, decision_insight)
        # Audit only non-HOLD monitor decisions to cut LLM load (EXIT/etc.).
        if decision.action != "HOLD":
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
        if candidate.action in {"BUY", "SELL"}:
            if not candidate.gates_passed:
                return False, "scanner_gates_failed"
            if candidate.confidence < self.config.min_scanner_confidence:
                return False, (
                    f"scanner_confidence={candidate.confidence:.1f}"
                    f"<{self.config.min_scanner_confidence:.1f}"
                )
            return True, "qualified"

        if (
            candidate.action == "WATCH"
            and self.config.allow_watch_soft_entry
        ):
            if not candidate.gates_passed:
                return False, "scanner_gates_failed"
            if candidate.confidence < self.config.min_watch_confidence:
                return False, (
                    f"watch_confidence={candidate.confidence:.1f}"
                    f"<{self.config.min_watch_confidence:.1f}"
                )
            return True, "watch_soft_entry"

        return False, f"scanner_action={candidate.action}"

    def _scanner_chart_conflict(self, scanner_action: str, chart_bias: str) -> str | None:
        if scanner_action == "BUY" and chart_bias == "BEARISH":
            return "scanner_BUY_vs_chart_BEARISH"
        if scanner_action == "SELL" and chart_bias == "BULLISH":
            return "scanner_SELL_vs_chart_BULLISH"
        return None

    def _load_learning(self) -> tuple[Any, dict[str, Any] | None]:
        """Load learning insight for Decision + LLM Journal Coach.

        Always return the raw LearningInsight object so PolicyPatch can be
        parsed/shadow-logged from ``insight.meta["llm"]``.

        Statistical score adjustments (hot/cold pattern boosts) are still
        gated by ``apply_learning_to_decision`` inside DecisionAgent callers:
        we pass ``insight`` only when that flag is on; otherwise callers get
        raw for policy loading then may choose not to apply stats.
        """
        try:
            raw = self.learning_agent.learn()
            advisory = {
                "total_trades": raw.total_trades,
                "hot_patterns": list(raw.hot_patterns),
                "cold_patterns": list(raw.cold_patterns),
                "worst_regime": raw.worst_regime,
                "min_confluence_recommended": raw.min_confluence_recommended,
                "applied_to_decision": self.config.apply_learning_to_decision,
                "llm_enabled": bool((raw.meta or {}).get("llm", {}).get("enabled")),
                "llm_model": (raw.meta or {}).get("llm", {}).get("model"),
            }
            # Always return raw so Journal Coach / PolicyPatch can run in shadow.
            # Decision score adjustments remain controlled by apply_learning_to_decision
            # via a separate flag checked by decide_entry consumers if needed.
            return raw, advisory
        except Exception as exc:
            return None, {"error": str(exc), "applied_to_decision": False}

    def _run_risk_gate(self, decision, *, position: PositionContext | None = None, candles: list[Candle] | None = None) -> RiskApproval:
        if decision.action in {"SKIP", "HOLD"}:
            return RiskApproval(approved=True, reason=f"noop_allowed={decision.action}", checks={"action": decision.action, "noop": True})
        return self.risk_agent.approve_execution(decision, position=position, candles=candles)

    def _load_policy(self, insight):
        """Learning Journal Coach: parse+validate LLM PolicyPatch (shadow-first).

        Returns (patch_or_None_for_decision, validation_dict_for_audit).
        A patch only reaches Decision when validation.applied is True
        (requires apply_llm_policy=True + confidence + sample threshold).
        """
        if insight is None:
            return None, None
        block = None
        meta = getattr(insight, "meta", None)
        if isinstance(meta, dict):
            block = meta.get("llm")
        raw_output = block.get("latest") if isinstance(block, dict) else None
        if not isinstance(raw_output, dict):
            return None, None
        try:
            patch = parse_policy_patch(raw_output)
            if patch is None:
                return None, None
            validation = validate_policy_patch(
                patch,
                total_trades=getattr(insight, "total_trades", 0),
                apply_enabled=self.config.apply_llm_policy,
                min_confidence=self.config.policy_min_confidence,
            )
            audit = {
                "patch": patch.to_dict(),
                "validation": validation.to_dict(),
                "apply_enabled": self.config.apply_llm_policy,
            }
            return (patch if validation.applied else None), audit
        except Exception as exc:  # noqa: BLE001 - policy must never break pipeline
            return None, {"error": str(exc), "apply_enabled": self.config.apply_llm_policy}


    def _propose_chart(self, reading, *, stage: str):
        """Chart LLM free-technique proposal; falls back to explain-only storage."""
        if self._chart_llm_client is None or not self._chart_llm_model:
            return reading
        meta = dict(reading.meta)
        try:
            if self.config.chart_llm_propose:
                output = self._chart_llm_client.chat_json(
                    system=proposal_system_prompt(),
                    user=json.dumps(
                        proposal_user_payload(reading, stage=stage), ensure_ascii=False
                    ),
                    max_tokens=1200,
                    temperature=0.2,
                )
            else:
                payload = {
                    "stage": stage,
                    "chart_reading": reading.to_dict(),
                    "instruction": "Explain chart reading. Do not change bias or levels.",
                }
                output = self._chart_llm_client.chat_json(
                    system="You are a read-only chart explanation assistant. Output JSON only.",
                    user=json.dumps(payload, ensure_ascii=False),
                    max_tokens=600,
                    temperature=0.2,
                )
            proposal = parse_chart_proposal(output, symbol=reading.symbol)
            validation = None
            if proposal is not None:
                validation = validate_chart_proposal(proposal, reading)
            meta["llm_proposal"] = {
                "enabled": True,
                "model": self._chart_llm_model,
                "provider_base_url": self._chart_llm_base_url,
                "mode": "propose" if self.config.chart_llm_propose else "explain",
                "raw": output,
                "proposal": proposal.to_dict() if proposal else None,
                "validation": validation.to_dict() if validation else None,
                "free_technique": True,
                "deterministic_fields_unchanged": True,
            }
            meta["llm_explanation"] = {
                "enabled": True,
                "model": self._chart_llm_model,
                "provider_base_url": self._chart_llm_base_url,
                "result": output,
                "deterministic_fields_unchanged": True,
                "via": "chart_proposal",
            }
        except Exception as exc:
            meta["llm_proposal"] = {
                "enabled": True,
                "model": self._chart_llm_model,
                "error": str(exc),
                "fallback": "deterministic_chart_only",
                "deterministic_fields_unchanged": True,
            }
            meta["llm_explanation"] = {
                "enabled": True,
                "model": self._chart_llm_model,
                "error": str(exc),
                "fallback": "deterministic_chart_only",
                "deterministic_fields_unchanged": True,
            }
        return replace(reading, meta=meta)

    def _adopt_chart_proposal(self, reading, decision: Decision) -> Decision:
        """Optionally replace EntryPlan with validated free-technique levels."""
        if not self.config.adopt_chart_proposal_levels:
            return decision
        if decision.action not in {"ENTRY_BUY", "ENTRY_SELL"}:
            return decision
        block = reading.meta.get("llm_proposal") if isinstance(reading.meta, dict) else None
        if not isinstance(block, dict):
            return decision
        validation = block.get("validation") or {}
        proposal_data = block.get("proposal")
        if not validation.get("accepted") or not isinstance(proposal_data, dict):
            meta = dict(decision.meta)
            meta["chart_proposal_adopted"] = False
            meta["chart_proposal_skip_reason"] = validation.get("reasons") or ["not_accepted"]
            return replace(decision, meta=meta)

        entry = proposal_data.get("proposed_entry")
        sl = proposal_data.get("proposed_sl")
        tp1 = proposal_data.get("proposed_tp1")
        if entry is None or sl is None or tp1 is None:
            return decision

        side = "BUY" if decision.action == "ENTRY_BUY" else "SELL"
        risk = abs(float(entry) - float(sl))
        rr = abs(float(tp1) - float(entry)) / risk if risk > 0 else 0.0
        old_plan = decision.entry_plan
        new_plan = EntryPlan(
            side=side,  # type: ignore[arg-type]
            entry_price=round(float(entry), 8),
            stop_loss=round(float(sl), 8),
            take_profit_1=round(float(tp1), 8),
            take_profit_2=(
                round(float(proposal_data["proposed_tp2"]), 8)
                if proposal_data.get("proposed_tp2") is not None
                else (old_plan.take_profit_2 if old_plan else None)
            ),
            take_profit_3=(
                round(float(proposal_data["proposed_tp3"]), 8)
                if proposal_data.get("proposed_tp3") is not None
                else (old_plan.take_profit_3 if old_plan else None)
            ),
            risk_reward=round(rr, 2),
            position_size_percent=old_plan.position_size_percent if old_plan else 1.0,
            entry_zone=old_plan.entry_zone if old_plan else None,
            # Entry execution is always immediate; chart levels remain inputs
            # for sizing and protection, not a reason to queue a limit order.
            order_type="MARKET",
            expires_in_seconds=old_plan.expires_in_seconds if old_plan else 900.0,
        )
        meta = dict(decision.meta)
        meta["chart_proposal_adopted"] = True
        meta["chart_proposal_methods"] = list(proposal_data.get("methods_used") or [])
        meta["chart_proposal_indicators"] = list(proposal_data.get("indicators_used") or [])
        meta["chart_proposal_techniques"] = list(proposal_data.get("techniques_used") or [])
        meta["entry_plan_source"] = "chart_llm_proposal"
        reasons = list(decision.reasons) + ["entry_plan_from_chart_llm_proposal"]
        return replace(decision, entry_plan=new_plan, reasons=reasons, meta=meta)

    def _audit_decision(self, reading, insight, decision, *, stage: str):
        if self._decision_llm_client is None or not self._decision_llm_model:
            return decision
        proposal_block = None
        if isinstance(reading.meta, dict):
            proposal_block = reading.meta.get("llm_proposal")
        payload = {
            "stage": stage,
            "chart_reading": reading.to_dict(),
            "chart_llm_proposal": proposal_block,
            "learning_insight": insight.to_dict() if insight is not None else None,
            "decision": decision.to_dict(),
            "instruction": (
                "Audit this decision using the deterministic chart reading and any "
                "free-technique chart proposal. "
                "You may vote SUPPORT or VETO. "
                "VETO only when risk/setup quality is poor. "
                "You must NOT invent a new ENTRY if decision is SKIP. "
                "You must NOT change entry/SL/TP numbers here. "
                "Output JSON keys: vote (SUPPORT|VETO|ABSTAIN), confidence (0-1), "
                "reasons (array), notes (string)."
            ),
        }
        try:
            output = self._decision_llm_client.chat_json(
                system=(
                    "You are the Decision audit agent. Output JSON only. "
                    "Prefer VETO over forcing trades. Never place orders."
                ),
                user=json.dumps(payload, ensure_ascii=False),
                max_tokens=500,
                temperature=0.1,
            )
            vote = str((output or {}).get("vote") or "ABSTAIN").strip().upper()
            conf = output.get("confidence") if isinstance(output, dict) else None
            try:
                conf_f = float(conf) if conf is not None else 0.0
            except (TypeError, ValueError):
                conf_f = 0.0
            if conf_f > 1.0:
                conf_f = conf_f / 100.0

            action_changed = False
            # Tier 1 safety: LLM audit may only veto ENTRY. Mandatory/structural
            # exits (EXIT) must never be turned into HOLD by the LLM, otherwise a
            # stop-loss / invalidation exit could be silently cancelled.
            if (
                self.config.decision_llm_can_veto
                and vote == "VETO"
                and conf_f >= self.config.decision_llm_veto_min_confidence
                and decision.action in {"ENTRY_BUY", "ENTRY_SELL"}
            ):
                final_action = "SKIP"
                action_changed = True
                reasons = list(decision.reasons) + [
                    f"decision_llm_veto conf={conf_f:.2f}",
                    *[str(r) for r in (output.get("reasons") or [])][:5],
                ]
                decision = replace(
                    decision,
                    action=final_action,  # type: ignore[arg-type]
                    entry_plan=None,
                    reasons=reasons,
                    confidence="LOW",
                )

            meta = dict(decision.meta)
            meta["llm_audit"] = {
                "enabled": True,
                "model": self._decision_llm_model,
                "provider_base_url": self._decision_llm_base_url,
                "result": output,
                "vote": vote,
                "vote_confidence": conf_f,
                "final_action_unchanged": not action_changed,
                "can_veto": self.config.decision_llm_can_veto,
            }
            return replace(decision, meta=meta)
        except Exception as exc:
            meta = dict(decision.meta)
            meta["llm_audit"] = {
                "enabled": True,
                "model": self._decision_llm_model,
                "error": str(exc),
                "fallback": "deterministic_decision_only",
                "final_action_unchanged": True,
            }
            return replace(decision, meta=meta)

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
