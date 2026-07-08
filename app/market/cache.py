from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.core.models import Candle
from app.market.storage import SQLiteCandleStorage


class HistoricalCandleCache:
    def __init__(self, storage: SQLiteCandleStorage | None = None, ttl_seconds: int = 900) -> None:
        self.storage = storage or SQLiteCandleStorage()
        self.ttl = timedelta(seconds=ttl_seconds)

    def get(self, exchange: str, symbol: str, timeframe: str, limit: int) -> list[Candle] | None:
        if self.is_expired(exchange, symbol, timeframe):
            return None

        candles = self.storage.load_candles(exchange, symbol, timeframe, limit)
        if len(candles) < limit:
            return None
        return candles[-limit:]

    def put(self, exchange: str, symbol: str, timeframe: str, candles: list[Candle]) -> None:
        self.storage.save_candles(exchange, timeframe, candles)
        self.storage.set_cache_updated_at(self._cache_key(exchange, symbol, timeframe), self._now().isoformat())

    def is_expired(self, exchange: str, symbol: str, timeframe: str) -> bool:
        updated_at = self.storage.get_cache_updated_at(self._cache_key(exchange, symbol, timeframe))
        if not updated_at:
            return True

        try:
            last_update = datetime.fromisoformat(updated_at)
        except ValueError:
            return True

        if last_update.tzinfo is None:
            last_update = last_update.replace(tzinfo=UTC)
        return self._now() - last_update > self.ttl

    def _cache_key(self, exchange: str, symbol: str, timeframe: str) -> str:
        return f"{exchange.lower()}:{symbol.upper()}:{timeframe}"

    def _now(self) -> datetime:
        return datetime.now(UTC)