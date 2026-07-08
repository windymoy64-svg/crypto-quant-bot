from __future__ import annotations


class BinanceAccountAPI:
    def __init__(self, transport: object) -> None:
        self.transport = transport

    def account(self) -> dict[str, object]:
        return self.transport.private_get("/api/v3/account")

    def open_orders(self, symbol: str | None = None) -> list[dict[str, object]]:
        params = {"symbol": self._normalize_symbol(symbol)} if symbol else None
        return self.transport.private_get("/api/v3/openOrders", params)

    def all_orders(self, symbol: str, limit: int = 500) -> list[dict[str, object]]:
        return self.transport.private_get(
            "/api/v3/allOrders",
            {"symbol": self._normalize_symbol(symbol), "limit": limit},
        )

    def my_trades(self, symbol: str, limit: int = 500) -> list[dict[str, object]]:
        return self.transport.private_get(
            "/api/v3/myTrades",
            {"symbol": self._normalize_symbol(symbol), "limit": limit},
        )

    def _normalize_symbol(self, symbol: str | None) -> str:
        return (symbol or "").replace("/", "").replace("-", "").upper()