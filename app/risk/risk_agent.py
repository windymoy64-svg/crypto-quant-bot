"""Risk & Portfolio Agent — final veto gate before execution.

Deterministic only. Wraps existing RiskManager for entry approval and
adds pipeline-level checks (data presence, action eligibility).
Does not call LLM. DecisionAgent cannot override a RiskAgent reject.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.core.models import Candle
from app.decision_agent.models import Decision
from app.executor_agent.models import PositionContext
from app.risk.manager import RiskManager, RiskSettings


RISK_POLICY_VERSION = "risk-1.1.0"


@dataclass(frozen=True)
class RiskApproval:
    """Final approval decision from the risk agent."""

    approved: bool
    hard_rejections: list[str] = field(default_factory=list)
    quantity: float = 0.0
    notional: float = 0.0
    risk_amount: float = 0.0
    risk_reward: float = 0.0
    reason: str = ""
    checks: dict[str, Any] = field(default_factory=dict)
    risk_policy_version: str = RISK_POLICY_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RiskAgent:
    """Portfolio / risk veto between Decision and Executor."""

    def __init__(
        self,
        *,
        risk_manager: RiskManager | None = None,
        settings: RiskSettings | None = None,
        cash: float = 10_000.0,
        equity: float = 10_000.0,
        open_positions: int = 0,
        current_exposure: float = 0.0,
        require_risk_gate: bool = True,
    ) -> None:
        self.risk_manager = risk_manager or RiskManager(settings)
        self.cash = cash
        self.equity = equity
        self.open_positions = open_positions
        self.current_exposure = current_exposure
        self.require_risk_gate = require_risk_gate

    def approve_execution(
        self,
        decision: Decision,
        *,
        position: PositionContext | None = None,
        candles: list[Candle] | None = None,
        cash: float | None = None,
        equity: float | None = None,
        open_positions: int | None = None,
        current_exposure: float | None = None,
    ) -> RiskApproval:
        """Return hard approve/reject for a Decision before Executor runs."""
        if not self.require_risk_gate:
            return RiskApproval(
                approved=True,
                reason="risk_gate_disabled",
                checks={"require_risk_gate": False},
            )

        if decision.action not in {"ENTRY_BUY", "ENTRY_SELL"}:
            if decision.action == "EXIT":
                if position is None or position.quantity <= 0:
                    return RiskApproval(
                        approved=False,
                        hard_rejections=["NO_POSITION_TO_EXIT"],
                        reason="no_position_to_exit",
                    )
                return RiskApproval(
                    approved=True,
                    quantity=position.quantity,
                    reason="exit_allowed",
                    checks={"action": decision.action},
                )
            return RiskApproval(
                approved=False,
                hard_rejections=["ACTION_NOT_EXECUTABLE"],
                reason=f"action_not_executable={decision.action}",
                checks={"action": decision.action},
            )

        plan = decision.entry_plan
        if plan is None:
            return RiskApproval(
                approved=False,
                hard_rejections=["MISSING_ENTRY_PLAN"],
                reason="missing_entry_plan",
            )

        candle_list = list(candles or [])
        if not candle_list:
            return RiskApproval(
                approved=False,
                hard_rejections=["MISSING_CANDLES"],
                reason="missing_candles_for_risk_eval",
            )

        entry = float(plan.entry_price)
        stop = float(plan.stop_loss)
        tp = float(plan.take_profit_1)
        if decision.action == "ENTRY_SELL":
            risk = abs(entry - stop)
            reward = abs(tp - entry)
            stop = entry - risk
            tp = entry + reward

        result = self.risk_manager.evaluate_entry(
            symbol=decision.symbol,
            timestamp=decision.timestamp or "",
            candles=candle_list,
            cash=float(cash if cash is not None else self.cash),
            equity=float(equity if equity is not None else self.equity),
            entry=entry,
            stop_loss=stop,
            take_profit=tp,
            open_positions=int(
                open_positions if open_positions is not None else self.open_positions
            ),
            current_exposure=float(
                current_exposure
                if current_exposure is not None
                else self.current_exposure
            ),
        )

        if not result.approved:
            return RiskApproval(
                approved=False,
                hard_rejections=[str(result.reason).upper()],
                reason=result.reason,
                checks=dict(result.checks),
                risk_reward=float(result.risk_reward or 0.0),
            )

        return RiskApproval(
            approved=True,
            quantity=float(result.quantity),
            notional=float(result.notional),
            risk_amount=float(result.risk_amount),
            risk_reward=float(result.risk_reward),
            reason="approved",
            checks=dict(result.checks),
        )
