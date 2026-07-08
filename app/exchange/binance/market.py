from __future__ import annotations

from datetime import UTC, datetime

from app.core.models import Candle
from app.exchange.binance.models import BinanceBookTicker, BinanceOrderBook, BinanceTickerPrice


class BinanceMarketAPI:
    def __init__(self, transport: object) -> None:
        self.transport = transport

    def exchange_info(self, symbol: str | None = None) -> dict[str, object]:
        params = {"symbol": self._normalize_symbol(symbol)} if symbol else None
        return self.transport.public_get("/api/v3/exchangeInfo", params)

    def latest_price(self, symbol: str | None = None) -> dict[str, object] | list[dict[str, object]]:
        params = {"symbol": self._normalize_symbol(symbol)} if symbol else None
        data = self.transport.public_get("/api/v3/ticker/price", params)
        if isinstance(data, list):
            return [BinanceTickerPrice.from_api(row).to_dict() for row in data]
        return BinanceTickerPrice.from_api(data).to_dict()

    def ticker_24h(self, symbol: str | None = None) -> dict[str, object] | list[dict[str, object]]:
        params = {"symbol": self._normalize_symbol(symbol)} if symbol else None
        return self.transport.public_get("/api/v3/ticker/24hr", params)

    def order_book(self, symbol: str, limit: int = 100) -> dict[str, object]:
        data = self.transport.public_get(
            "/api/v3/depth",
            {"symbol": self._normalize_symbol(symbol), "limit": limit},
        )
        return BinanceOrderBook.from_api(data).to_dict()

    def klines(self, symbol: str, interval: str = "1h", limit: int = 100) -> list[Candle]:
        rows = self.transport.public_get(
            "/api/v3/klines",
            {"symbol": self._normalize_symbol(symbol), "interval": interval, "limit": limit},
        )
        return [
            Candle(
                symbol=symbol,
                timestamp=self._format_timestamp(row[0]),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
            )
            for row in rows
        ]

    def book_ticker(self, symbol: str | None = None) -> dict[str, object] | list[dict[str, object]]:
        params = {"symbol": self._normalize_symbol(symbol)} if symbol else None
        data = self.transport.public_get("/api/v3/ticker/bookTicker", params)
        if isinstance(data, list):
            return [BinanceBookTicker.from_api(row).to_dict() for row in data]
        return BinanceBookTicker.from_api(data).to_dict()

    def _normalize_symbol(self, symbol: str | None) -> str:
        return (symbol or "").replace("/", "").replace("-", "").upper()

    def _format_timestamp(self, value: int | float | str) -> str:
        return datetime.fromtimestamp(float(value) / 1000, tz=UTC).isoformat()