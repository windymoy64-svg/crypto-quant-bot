"""Executor Agent — translates Decisions into exchange orders.

Handles order construction, risk sizing, safety checks, and execution.
Supports dry-run mode (default) and live mode with explicit opt-in.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from app.decision_agent.models import Decision, EntryPlan
from app.executor_agent.models import (
    ExecutionPlan,
    ExecutionReport,
    ExecutionResult,
    OrderRequest,
    OrderSide,
    OrderType,
    PositionContext,
)

DEFAULT_RISK_PERCENT = 1.0
MAX_POSITION_SIZE_PERCENT = 15.0
DEFAULT_LEVERAGE = 1


class ExecutorAgent:
    """Translates Decision into executable orders.

    Default: dry-run (simulate fills). Set live=True + exchange adapter for real.
    """

    def __init__(
        self,
        balance: float = 10_000.0,
        risk_percent: float = DEFAULT_RISK_PERCENT,
        max_position_pct: float = MAX_POSITION_SIZE_PERCENT,
        leverage: int = DEFAULT_LEVERAGE,
        live: bool = False,
        exchange_adapter: Any = None,
    ) -> None:
        self.balance = balance
        self.risk_percent = risk_percent
        self.max_position_pct = max_position_pct
        self.leverage = leverage
        self.live = live
        self._exchange = exchange_adapter

    def execute(
        self,
        decision: Decision,
        position: PositionContext | None = None,
    ) -> ExecutionReport:
        """Execute a Decision — main entry point."""
        now = datetime.now(tz=UTC).isoformat()

        if decision.action in ("SKIP", "HOLD"):
            return self._noop_report(decision, now)
        if decision.action in ("ENTRY_BUY", "ENTRY_SELL"):
            return self._execute_entry(decision, now)
        if decision.action == "EXIT":
            return self._execute_exit(decision, position, now)
        return self._error_report(decision, now, "unknown_action")

    def _execute_entry(self, decision: Decision, now: str) -> ExecutionReport:
        plan = decision.entry_plan
        if plan is None:
            return self._error_report(decision, now, "no_entry_plan")
        if plan.entry_price <= 0 or plan.stop_loss <= 0:
            return self._error_report(decision, now, "invalid_prices")

        quantity = self._calculate_quantity(plan)
        if quantity <= 0:
            return self._error_report(decision, now, "zero_quantity")

        entry_side: OrderSide = "BUY" if decision.action == "ENTRY_BUY" else "SELL"
        sl_side: OrderSide = "SELL" if entry_side == "BUY" else "BUY"

        orders: list[OrderRequest] = [
            OrderRequest(
                symbol=decision.symbol, side=entry_side, order_type="LIMIT",
                quantity=quantity, price=plan.entry_price,
                meta={"role": "entry"},
            ),
            OrderRequest(
                symbol=decision.symbol, side=sl_side, order_type="STOP_MARKET",
                quantity=quantity, stop_price=plan.stop_loss, reduce_only=True,
                meta={"role": "stop_loss"},
            ),
        ]

        # TP orders split 30/30/40
        tp_fracs = [0.30, 0.30, 0.40]
        tp_prices = [plan.take_profit_1, plan.take_profit_2, plan.take_profit_3]
        for i, (frac, tp) in enumerate(zip(tp_fracs, tp_prices)):
            if tp is None or tp <= 0:
                continue
            tp_qty = round(quantity * frac, 8)
            if tp_qty > 0:
                orders.append(OrderRequest(
                    symbol=decision.symbol, side=sl_side, order_type="LIMIT",
                    quantity=tp_qty, price=tp, reduce_only=True,
                    meta={"role": f"take_profit_{i+1}"},
                ))

        return self._finalize(decision, orders, now)

    def _execute_exit(
        self,
        decision: Decision,
        position: PositionContext | None,
        now: str,
    ) -> ExecutionReport:
        if position is None or position.quantity <= 0:
            return self._error_report(decision, now, "position_context_required")

        exit_plan = decision.exit_plan
        urgency = exit_plan.urgency if exit_plan else "NEXT_CANDLE"
        order_type: OrderType = "MARKET" if urgency == "IMMEDIATE" else "LIMIT"
        price = (
            exit_plan.suggested_exit_price
            if exit_plan and exit_plan.suggested_exit_price
            else position.current_price
        )
        if order_type == "LIMIT" and (price is None or price <= 0):
            order_type = "MARKET"

        orders = [OrderRequest(
            symbol=decision.symbol,
            side="SELL" if position.side == "BUY" else "BUY",
            order_type=order_type,
            quantity=position.quantity,
            price=price,
            reduce_only=True,
            meta={"role": "exit", "reason": exit_plan.reason if exit_plan else "unknown"},
        )]
        return self._finalize(decision, orders, now)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _calculate_quantity(self, plan: EntryPlan) -> float:
        risk_amount = self.balance * (self.risk_percent / 100)
        risk_per_unit = abs(plan.entry_price - plan.stop_loss)
        if risk_per_unit <= 0:
            return 0.0
        quantity = (risk_amount / risk_per_unit) * self.leverage
        max_notional = self.balance * (self.max_position_pct / 100) * self.leverage
        max_qty = max_notional / plan.entry_price if plan.entry_price > 0 else 0
        return round(min(quantity, max_qty), 8)

    def _finalize(
        self, decision: Decision, orders: list[OrderRequest], now: str,
    ) -> ExecutionReport:
        exec_plan = ExecutionPlan(
            decision_action=decision.action,
            symbol=decision.symbol,
            orders=orders,
            timestamp=now,
            dry_run=not self.live,
        )
        results = self._send_orders(orders, now)
        filled_qty = sum(r.filled_quantity for r in results if r.is_success)
        entry_results = [r for r in results if r.is_success and r.meta.get("role") == "entry"]
        avg_price = (
            sum(r.average_price * r.filled_quantity for r in entry_results)
            / sum(r.filled_quantity for r in entry_results)
            if entry_results and sum(r.filled_quantity for r in entry_results) > 0
            else 0.0
        )
        total_fees = sum(r.fees for r in results)
        return ExecutionReport(
            plan=exec_plan, results=results,
            success=any(r.is_success for r in results),
            total_filled_quantity=filled_qty,
            average_entry_price=avg_price,
            total_fees=total_fees, timestamp=now,
        )

    def _send_orders(self, orders: list[OrderRequest], now: str) -> list[ExecutionResult]:
        if self.live:
            # Live mode never falls back to simulation. If the operator asked
            # for live execution without wiring an adapter, every order must be
            # rejected so nothing is submitted implicitly.
            return self._send_live(orders, now)
        return self._simulate(orders, now)

    def _simulate(self, orders: list[OrderRequest], now: str) -> list[ExecutionResult]:
        results: list[ExecutionResult] = []
        for order in orders:
            fill_price = order.price or order.stop_price or 0.0
            role = str(order.meta.get("role", ""))
            is_immediate = role in {"entry", "exit"}
            status = "FILLED" if is_immediate else "SUBMITTED"
            filled_quantity = order.quantity if is_immediate else 0.0
            results.append(ExecutionResult(
                status=status,
                order_id=f"sim_{uuid.uuid4().hex[:8]}",
                symbol=order.symbol, side=order.side, order_type=order.order_type,
                requested_quantity=order.quantity, filled_quantity=filled_quantity,
                average_price=fill_price, timestamp=now,
                fees=(fill_price * filled_quantity * 0.0004),
                meta=order.meta,
            ))
        return results

    def _send_live(self, orders: list[OrderRequest], now: str) -> list[ExecutionResult]:
        # Live mode requires an adapter. Without one, every order is rejected
        # so nothing is submitted implicitly.
        if self._exchange is None:
            return [
                ExecutionResult(
                    status="REJECTED",
                    order_id=f"live_{uuid.uuid4().hex[:8]}",
                    symbol=order.symbol, side=order.side, order_type=order.order_type,
                    requested_quantity=order.quantity, filled_quantity=0.0,
                    average_price=0.0, timestamp=now,
                    reason="exchange_adapter_not_configured", meta=order.meta,
                )
                for order in orders
            ]

        # Delegate to the adapter. Any adapter must expose ``place_order``.
        results: list[ExecutionResult] = []
        for order in orders:
            try:
                results.append(self._exchange.place_order(order, timestamp=now))
            except Exception as exc:  # noqa: BLE001
                results.append(ExecutionResult(
                    status="REJECTED",
                    order_id=f"live_{uuid.uuid4().hex[:8]}",
                    symbol=order.symbol, side=order.side, order_type=order.order_type,
                    requested_quantity=order.quantity, filled_quantity=0.0,
                    average_price=0.0, timestamp=now,
                    reason=f"adapter_error: {exc}", meta=order.meta,
                ))
        return results

    def _noop_report(self, decision: Decision, now: str) -> ExecutionReport:
        return ExecutionReport(
            plan=ExecutionPlan(
                decision_action=decision.action, symbol=decision.symbol,
                orders=[], timestamp=now, dry_run=not self.live,
            ),
            results=[], success=True, total_filled_quantity=0.0,
            average_entry_price=0.0, total_fees=0.0, timestamp=now,
        )

    def _error_report(self, decision: Decision, now: str, error: str) -> ExecutionReport:
        return ExecutionReport(
            plan=ExecutionPlan(
                decision_action=decision.action, symbol=decision.symbol,
                orders=[], timestamp=now, dry_run=not self.live,
            ),
            results=[], success=False, total_filled_quantity=0.0,
            average_entry_price=0.0, total_fees=0.0, timestamp=now,
            errors=[error],
        )

