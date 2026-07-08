from __future__ import annotations

from app.live.account import AccountSnapshot, OpenOrderSummary
from app.live.config import LiveConfig
from app.live.exchange_rules import normalize_symbol
from app.live.models import LiveOrder


class AccountPreflightValidator:
    def __init__(self, config: LiveConfig | None = None) -> None:
        self.config = config or LiveConfig()

    def validate(
        self,
        *,
        order: LiveOrder,
        account_snapshot: AccountSnapshot,
        open_orders: list[OpenOrderSummary],
        daily_orders: int = 0,
        exchange_validated: bool = True,
    ):
        from app.live.preflight import PreflightResult

        if not exchange_validated:
            return PreflightResult(False, "exchange_validator_not_passed", account_snapshot, open_orders)
        if self.config.require_can_trade and not account_snapshot.can_trade:
            return PreflightResult(False, "account_cannot_trade", account_snapshot, open_orders)
        if self.config.require_spot_permission and "SPOT" not in account_snapshot.permissions:
            return PreflightResult(False, "account_spot_permission_required", account_snapshot, open_orders)
        if account_snapshot.free_balance("USDT") < self.config.minimum_quote_balance:
            return PreflightResult(False, "account_quote_balance_below_minimum", account_snapshot, open_orders)
        if account_snapshot.free_balance("USDT") < order.quote_amount:
            return PreflightResult(False, "account_quote_balance_insufficient", account_snapshot, open_orders)
        if daily_orders >= self.config.max_daily_orders:
            return PreflightResult(False, "account_daily_order_limit_reached", account_snapshot, open_orders)
        if len(open_orders) >= self.config.max_open_orders:
            return PreflightResult(False, "account_open_order_limit_reached", account_snapshot, open_orders)
        symbol = normalize_symbol(order.symbol)
        if any(existing.symbol == symbol and existing.side == order.side for existing in open_orders):
            return PreflightResult(False, "account_duplicate_order_for_symbol", account_snapshot, open_orders)
        return PreflightResult(True, "account_preflight_approved", account_snapshot, open_orders)