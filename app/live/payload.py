from __future__ import annotations

from app.live.models import LiveOrder


class BinancePayloadBuilder:
    def build_market_buy(self, order: LiveOrder) -> dict[str, object]:
        if order.side != "BUY":
            raise ValueError("Only BUY payloads are supported for Sprint 20A")
        if order.order_type != "MARKET":
            raise ValueError("Only MARKET payloads are supported for Sprint 20A")
        return {
            "symbol": self._format_symbol(order.symbol),
            "side": "BUY",
            "type": "MARKET",
            "quoteOrderQty": round(order.quote_amount, 8),
        }

    def _format_symbol(self, symbol: str) -> str:
        return symbol.replace("/", "").replace("-", "").upper()
