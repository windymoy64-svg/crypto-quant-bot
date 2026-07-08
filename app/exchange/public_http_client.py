from __future__ import annotations

import json
from datetime import UTC, datetime
from urllib.parse import urlencode
from urllib.request import urlopen

from app.core.models import Candle
from app.exchange.base import ExchangeClient


class PublicHttpExchangeClient(ExchangeClient):
    def __init__(self, exchange_id: str = "binance", timeout_seconds: int = 10) -> None:
        self.exchange_id = exchange_id.lower()
        self.timeout_seconds = timeout_seconds

    def fetch_candles(self, symbol: str, timeframe: str = "1m", limit: int = 100) -> list[Candle]:
        if self.exchange_id == "binance":
            return self._fetch_binance_candles(symbol, timeframe, limit)
        if self.exchange_id == "okx":
            return self._fetch_okx_candles(symbol, timeframe, limit)
        raise ValueError(f"Unsupported public HTTP exchange: {self.exchange_id}")

    def fetch_ticker(self, symbol: str) -> dict[str, float | str]:
        if self.exchange_id == "binance":
            market_symbol = self._binance_symbol(symbol)
            data = self._get_json(
                "https://api.binance.com/api/v3/ticker/24hr",
                {"symbol": market_symbol},
            )
            return {
                "symbol": symbol,
                "bid": float(data.get("bidPrice") or 0),
                "ask": float(data.get("askPrice") or 0),
                "last": float(data.get("lastPrice") or 0),
                "volume": float(data.get("volume") or 0),
            }
        if self.exchange_id == "okx":
            market_symbol = self._okx_symbol(symbol)
            data = self._get_json(
                "https://www.okx.com/api/v5/market/ticker",
                {"instId": market_symbol},
            )
            row = data["data"][0]
            return {
                "symbol": symbol,
                "bid": float(row.get("bidPx") or 0),
                "ask": float(row.get("askPx") or 0),
                "last": float(row.get("last") or 0),
                "volume": float(row.get("vol24h") or 0),
            }
        raise ValueError(f"Unsupported public HTTP exchange: {self.exchange_id}")

    def _fetch_binance_candles(self, symbol: str, timeframe: str, limit: int) -> list[Candle]:
        market_symbol = self._binance_symbol(symbol)
        rows = self._get_json(
            "https://api.binance.com/api/v3/klines",
            {"symbol": market_symbol, "interval": timeframe, "limit": limit},
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

    def _fetch_okx_candles(self, symbol: str, timeframe: str, limit: int) -> list[Candle]:
        market_symbol = self._okx_symbol(symbol)
        data = self._get_json(
            "https://www.okx.com/api/v5/market/candles",
            {"instId": market_symbol, "bar": timeframe, "limit": limit},
        )
        rows = list(reversed(data["data"]))
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

    def _get_json(self, url: str, params: dict[str, str | int]) -> object:
        query = urlencode(params)
        with urlopen(f"{url}?{query}", timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))

    def _format_timestamp(self, value: int | float | str) -> str:
        return datetime.fromtimestamp(float(value) / 1000, tz=UTC).isoformat()

    def _binance_symbol(self, symbol: str) -> str:
        return symbol.replace("/", "").replace("-", "").upper()

    def _okx_symbol(self, symbol: str) -> str:
        return symbol.replace("/", "-").upper()
