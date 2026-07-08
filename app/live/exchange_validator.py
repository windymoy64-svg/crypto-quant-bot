from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Protocol

from app.live.exchange_rules import ExchangeInfo, normalize_symbol
from app.live.models import LiveOrder, LiveValidationResult


class ExchangeInfoSource(Protocol):
    def get(self, *, force_refresh: bool = False) -> ExchangeInfo:
        ...


class ExchangeValidator:
    def __init__(self, source: ExchangeInfo | ExchangeInfoSource) -> None:
        self.source = source

    def validate(self, order: LiveOrder) -> LiveValidationResult:
        info = self.source.get() if hasattr(self.source, "get") else self.source
        symbol_key = normalize_symbol(order.symbol)
        rules = info.get_symbol(symbol_key)
        if rules is None:
            return LiveValidationResult(False, f"exchange_symbol_not_found:{symbol_key}")
        if rules.status != "TRADING":
            return LiveValidationResult(False, f"exchange_symbol_not_trading:{symbol_key}:{rules.status}")
        if order.order_type not in rules.orderTypes:
            return LiveValidationResult(False, f"exchange_order_type_not_allowed:{symbol_key}:{order.order_type}")

        quantity_check = self._validate_quantity(order.quantity, rules.filters.get("LOT_SIZE"), "lot_size")
        if not quantity_check.valid:
            return quantity_check
        market_quantity_check = self._validate_quantity(order.quantity, rules.filters.get("MARKET_LOT_SIZE"), "market_lot_size")
        if not market_quantity_check.valid:
            return market_quantity_check
        price_check = self._validate_price(order.price, rules.filters.get("PRICE_FILTER"))
        if not price_check.valid:
            return price_check
        notional_check = self._validate_notional(order.quote_amount, rules.filters.get("MIN_NOTIONAL"), rules.filters.get("NOTIONAL"))
        if not notional_check.valid:
            return notional_check
        return LiveValidationResult(True, "exchange_rules_approved")

    def _validate_quantity(self, quantity: float, rule: dict[str, object] | None, label: str) -> LiveValidationResult:
        if not rule:
            return LiveValidationResult(True, "skipped")
        value = self._decimal(quantity)
        min_qty = self._decimal(rule.get("minQty", "0"))
        max_qty = self._decimal(rule.get("maxQty", "0"))
        step_size = self._decimal(rule.get("stepSize", "0"))
        if min_qty > 0 and value < min_qty:
            return LiveValidationResult(False, f"exchange_{label}_min_qty:{quantity}<{min_qty}")
        if max_qty > 0 and value > max_qty:
            return LiveValidationResult(False, f"exchange_{label}_max_qty:{quantity}>{max_qty}")
        if step_size > 0 and not self._aligned(value, step_size, min_qty):
            return LiveValidationResult(False, f"exchange_{label}_step_size:{quantity}:{step_size}")
        return LiveValidationResult(True, "approved")

    def _validate_price(self, price: float, rule: dict[str, object] | None) -> LiveValidationResult:
        if not rule:
            return LiveValidationResult(True, "skipped")
        value = self._decimal(price)
        min_price = self._decimal(rule.get("minPrice", "0"))
        max_price = self._decimal(rule.get("maxPrice", "0"))
        tick_size = self._decimal(rule.get("tickSize", "0"))
        if min_price > 0 and value < min_price:
            return LiveValidationResult(False, f"exchange_price_min:{price}<{min_price}")
        if max_price > 0 and value > max_price:
            return LiveValidationResult(False, f"exchange_price_max:{price}>{max_price}")
        if tick_size > 0 and not self._aligned(value, tick_size, min_price):
            return LiveValidationResult(False, f"exchange_price_tick_size:{price}:{tick_size}")
        return LiveValidationResult(True, "approved")

    def _validate_notional(
        self,
        quote_amount: float,
        min_notional_rule: dict[str, object] | None,
        notional_rule: dict[str, object] | None,
    ) -> LiveValidationResult:
        value = self._decimal(quote_amount)
        minimum = self._decimal((notional_rule or min_notional_rule or {}).get("minNotional", "0"))
        maximum = self._decimal((notional_rule or {}).get("maxNotional", "0"))
        if minimum > 0 and value < minimum:
            return LiveValidationResult(False, f"exchange_min_notional:{quote_amount}<{minimum}")
        if maximum > 0 and value > maximum:
            return LiveValidationResult(False, f"exchange_max_notional:{quote_amount}>{maximum}")
        return LiveValidationResult(True, "approved")

    def _decimal(self, value: object) -> Decimal:
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return Decimal("0")

    def _aligned(self, value: Decimal, step: Decimal, minimum: Decimal) -> bool:
        baseline = minimum if minimum > 0 else Decimal("0")
        return (value - baseline) % step == 0