from __future__ import annotations

from app.exchange.binance.client import BinanceConnector
from app.live.exchange_rules import normalize_symbol


class BinanceOrderMonitor:
    def __init__(self, connector: BinanceConnector | None = None) -> None:
        self.connector = connector or BinanceConnector()

    def order_status(self, symbol: str, order_id: int | None = None, client_order_id: str | None = None) -> dict[str, object]:
        params: dict[str, object] = {"symbol": normalize_symbol(symbol)}
        if order_id is not None:
            params["orderId"] = order_id
        if client_order_id:
            params["origClientOrderId"] = client_order_id
        return self.connector.private_get("/api/v3/order", params)

    def open_orders(self, symbol: str | None = None) -> object:
        params = {"symbol": normalize_symbol(symbol)} if symbol else None
        return self.connector.private_get("/api/v3/openOrders", params)

    def my_trades(self, symbol: str, limit: int = 50) -> object:
        return self.connector.private_get("/api/v3/myTrades", {"symbol": normalize_symbol(symbol), "limit": limit})