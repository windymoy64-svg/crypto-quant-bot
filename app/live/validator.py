from __future__ import annotations

from app.core.models import TradingSignal
from app.live.models import LiveOrder, LiveValidationResult
from app.risk.manager import RiskDecision


class LiveOrderValidator:
    def validate(
        self,
        *,
        signal: TradingSignal,
        risk_decision: RiskDecision,
        order: LiveOrder,
    ) -> LiveValidationResult:
        if not order.symbol.strip():
            return LiveValidationResult(False, "symbol_required")
        if order.quantity <= 0:
            return LiveValidationResult(False, "quantity_must_be_positive")
        if order.quote_amount <= 0:
            return LiveValidationResult(False, "quote_amount_must_be_positive")
        if signal.action != "BUY" or order.side != "BUY":
            return LiveValidationResult(False, "only_buy_action_supported")
        if not risk_decision.approved:
            return LiveValidationResult(False, f"risk_not_approved:{risk_decision.reason}")
        return LiveValidationResult(True, "approved")
