from __future__ import annotations

from datetime import UTC, datetime

from app.core.models import Candle
from app.exchange.base import ExchangeClient


class CcxtExchangeClient(ExchangeClient):
    def __init__(
        self,
        exchange_id: str = "binance",
        *,
        api_key: str | None = None,
        secret: str | None = None,
        password: str | None = None,
    ) -> None:
        import ccxt

        exchange_class = getattr(ccxt, exchange_id)
        options: dict[str, object] = {"enableRateLimit": True}
        if api_key:
            options["apiKey"] = api_key
        if secret:
            options["secret"] = secret
        if password:
            options["password"] = password
        self.exchange = exchange_class(options)

    def fetch_candles(self, symbol: str, timeframe: str = "1m", limit: int = 100) -> list[Candle]:
        rows = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
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

    def fetch_ticker(self, symbol: str) -> dict[str, float | str]:
        ticker = self.exchange.fetch_ticker(symbol)
        return {
            "symbol": symbol,
            "bid": float(ticker.get("bid") or 0),
            "ask": float(ticker.get("ask") or 0),
            "last": float(ticker.get("last") or 0),
        }

    def fetch_balance(self) -> dict[str, object]:
        return self.exchange.fetch_balance()

    def create_market_order(self, symbol: str, side: str, amount: float) -> dict[str, object]:
        return self.exchange.create_order(symbol=symbol, type="market", side=side, amount=amount)

    def _format_timestamp(self, value: int | float | str) -> str:
        if isinstance(value, str):
            return value
        return datetime.fromtimestamp(float(value) / 1000, tz=UTC).isoformat()
