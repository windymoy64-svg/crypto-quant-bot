from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime

from app.live.account import OpenOrderSummary
from app.live.config import LiveConfig
from app.live.cooldown import SymbolCooldown
from app.live.exchange_rules import normalize_symbol
from app.live.models import LiveOrder
from app.live.order_history import OrderHistory


@dataclass(frozen=True)
class IntentDecision:
    approved: bool
    reason: str
    cooldown: bool = False
    duplicate: bool = False
    position_exists: bool = False
    same_side_open: bool = False
    recent_signal: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class OrderIntentEngine:
    def __init__(
        self,
        config: LiveConfig | None = None,
        *,
        history: OrderHistory | None = None,
        cooldown: SymbolCooldown | None = None,
        position_symbols: set[str] | None = None,
    ) -> None:
        self.config = config or LiveConfig()
        self.history = history or OrderHistory()
        self.cooldown = cooldown or SymbolCooldown(self.config.cooldown_seconds)
        self.position_symbols = {normalize_symbol(symbol) for symbol in position_symbols or set()}

    def evaluate(
        self,
        order: LiveOrder,
        *,
        open_orders: list[OpenOrderSummary] | None = None,
        now: float | None = None,
    ) -> IntentDecision:
        symbol = normalize_symbol(order.symbol)
        if symbol in self.position_symbols:
            return IntentDecision(False, "intent_position_exists", position_exists=True)
        if self._same_side_open(order, open_orders or []):
            return IntentDecision(False, "intent_same_side_open_order", same_side_open=True)
        if self.history.active_same_side(symbol, order.side):
            return IntentDecision(False, "intent_duplicate_order", duplicate=True, same_side_open=True)
        if self.history.count_same_symbol(symbol) >= self.config.max_same_symbol_orders:
            return IntentDecision(False, "intent_max_same_symbol_orders", duplicate=True)
        if self.cooldown.active(symbol, now):
            return IntentDecision(False, "intent_symbol_cooldown", cooldown=True, recent_signal=True)
        if self._recent_same_signal(order, now):
            return IntentDecision(False, "intent_recent_signal", duplicate=True, recent_signal=True)
        self.cooldown.mark(symbol, now)
        self.history.add(symbol, order.side, "PREPARED", order.timestamp)
        return IntentDecision(True, "intent_approved")

    def _same_side_open(self, order: LiveOrder, open_orders: list[OpenOrderSummary]) -> bool:
        symbol = normalize_symbol(order.symbol)
        return any(normalize_symbol(item.symbol) == symbol and item.side == order.side for item in open_orders)

    def _recent_same_signal(self, order: LiveOrder, now: float | None) -> bool:
        latest = self.history.latest_same_side(order.symbol, order.side)
        if latest is None or self.config.cooldown_seconds <= 0:
            return False
        try:
            previous = datetime.fromisoformat(latest.timestamp.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return False
        current = float(now if now is not None else datetime.now().timestamp())
        return (current - previous) < self.config.cooldown_seconds