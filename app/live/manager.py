from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from app.core.models import TradingSignal
from app.live.config import LiveConfig
from app.live.exchange_validator import ExchangeValidator
from app.live.executor import LiveExecutor
from app.live.intent import OrderIntentEngine
from app.live.models import LiveExecutionResult, LiveOrder
from app.live.payload import BinancePayloadBuilder
from app.live.preflight import AccountPreflightEngine
from app.live.submission import BinanceOrderSubmissionEngine
from app.live.validator import LiveOrderValidator
from app.risk.manager import RiskDecision


class LiveTradingManager:
    def __init__(
        self,
        config: LiveConfig | None = None,
        *,
        validator: LiveOrderValidator | None = None,
        exchange_validator: ExchangeValidator | None = None,
        account_preflight: AccountPreflightEngine | None = None,
        order_intent: OrderIntentEngine | None = None,
        payload_builder: BinancePayloadBuilder | None = None,
        submission_engine: BinanceOrderSubmissionEngine | None = None,
        executor: LiveExecutor | None = None,
        log_path: str | Path = "logs/live_dry_run.jsonl",
    ) -> None:
        self.config = config or LiveConfig()
        self.validator = validator or LiveOrderValidator()
        self.exchange_validator = exchange_validator
        self.account_preflight = account_preflight
        self.order_intent = order_intent
        self.payload_builder = payload_builder or BinancePayloadBuilder()
        self.submission_engine = submission_engine
        self.executor = executor or LiveExecutor(self.config)
        self.log_path = Path(log_path)
        self._daily_orders: dict[str, int] = {}

    def execute(self, signal: TradingSignal, risk_decision: RiskDecision) -> LiveExecutionResult:
        order = self._build_order(signal, risk_decision)
        validation = self.validator.validate(signal=signal, risk_decision=risk_decision, order=order)
        if not validation.valid:
            result = LiveExecutionResult(
                mode="DRY_RUN" if self.config.dry_run else "LIVE_DISABLED",
                status="rejected",
                reason=validation.reason,
                order=order,
            )
            self._log_result(result)
            return result

        if self.exchange_validator is not None:
            exchange_validation = self.exchange_validator.validate(order)
            if not exchange_validation.valid:
                result = LiveExecutionResult(
                    mode="DRY_RUN" if self.config.dry_run else "LIVE_DISABLED",
                    status="rejected",
                    reason=exchange_validation.reason,
                    order=order,
                )
                self._log_result(result)
                return result

        preflight_open_orders = []
        if self.account_preflight is not None:
            preflight = self.account_preflight.validate(
                order,
                daily_orders=self._daily_orders_for(order.timestamp),
                exchange_validated=self.exchange_validator is not None,
            )
            if not preflight.approved:
                result = LiveExecutionResult(
                    mode="DRY_RUN" if self.config.dry_run else "LIVE_DISABLED",
                    status="rejected",
                    reason=preflight.reason,
                    order=order,
                    meta={"preflight": preflight.to_dict()},
                )
                self._log_result(result)
                return result
            preflight_open_orders = preflight.open_orders

        if self.order_intent is not None:
            intent = self.order_intent.evaluate(order, open_orders=preflight_open_orders)
            if not intent.approved:
                result = LiveExecutionResult(
                    mode="DRY_RUN" if self.config.dry_run else "LIVE_DISABLED",
                    status="rejected",
                    reason=intent.reason,
                    order=order,
                    meta={"intent": intent.to_dict()},
                )
                self._log_result(result)
                return result

        if not self._daily_order_allowed(order.timestamp):
            result = LiveExecutionResult(
                mode="DRY_RUN" if self.config.dry_run else "LIVE_DISABLED",
                status="rejected",
                reason="max_daily_orders_reached",
                order=order,
            )
            self._log_result(result)
            return result

        payload = self.payload_builder.build_market_buy(order)
        if self.submission_engine is not None:
            submission = self.submission_engine.submit_order(payload)
            result = LiveExecutionResult(
                mode="LIVE" if submission.success else "LIVE_BLOCKED",
                status=submission.status or ("submitted" if submission.success else "rejected"),
                payload=payload,
                reason="order_submitted" if submission.success else str(submission.raw.get("reason", "submission_blocked")),
                order=order,
                meta={"submission": submission.to_dict()},
            )
            if submission.success:
                self._record_daily_order(order.timestamp)
            self._log_result(result)
            return result

        result = self.executor.execute(payload=payload, order=order)
        self._record_daily_order(order.timestamp)
        self._log_result(result)
        return result

    def _build_order(self, signal: TradingSignal, risk_decision: RiskDecision) -> LiveOrder:
        take_profit = signal.take_profit[0] if signal.take_profit else risk_decision.take_profit
        return LiveOrder(
            symbol=signal.symbol,
            side="BUY",
            order_type=self.config.order_type,
            quantity=risk_decision.quantity,
            quote_amount=self.config.default_quote_amount,
            price=signal.entry,
            stop_loss=signal.stop_loss,
            take_profit=take_profit,
            timestamp=risk_decision.timestamp or datetime.now(UTC).isoformat(),
        )

    def _daily_order_allowed(self, timestamp: str) -> bool:
        day = self._day_key(timestamp)
        return self._daily_orders.get(day, 0) < self.config.max_daily_orders

    def _daily_orders_for(self, timestamp: str) -> int:
        return self._daily_orders.get(self._day_key(timestamp), 0)

    def _record_daily_order(self, timestamp: str) -> None:
        day = self._day_key(timestamp)
        self._daily_orders[day] = self._daily_orders.get(day, 0) + 1

    def _day_key(self, timestamp: str) -> str:
        return timestamp[:10] if timestamp else datetime.now(UTC).date().isoformat()

    def _log_result(self, result: LiveExecutionResult) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.write_text("", encoding="utf-8") if not self.log_path.exists() else None
        with self.log_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(result.to_dict(), sort_keys=True) + "\n")
