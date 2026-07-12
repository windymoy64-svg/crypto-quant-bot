from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.core.models import Candle
from app.market.cache import HistoricalCandleCache


DownloadFn = Callable[[str, str, int], list[Candle]]


@dataclass(frozen=True)
class HistoryLoadResult:
    symbol: str
    exchange: str
    timeframe: str
    candles: list[Candle]
    source: str
    warning: str | None = None


class HistoricalMarketDataEngine:
    def __init__(self, exchange: str, cache: HistoricalCandleCache | None = None) -> None:
        self.exchange = exchange
        self.cache = cache or HistoricalCandleCache()

    def load_history(
        self,
        symbol: str,
        timeframe: str,
        limit: int,
        downloader: DownloadFn,
        force_refresh: bool = False,
    ) -> HistoryLoadResult:
        # Simbol yang sedang di-entry (force_refresh) wajib mengambil harga
        # realtime, jadi cache dilewati agar tidak menyajikan data basi.
        cached = (
            None
            if force_refresh
            else self.cache.get(self.exchange, symbol, timeframe, limit)
        )
        if cached:
            return HistoryLoadResult(
                symbol=symbol,
                exchange=self.exchange,
                timeframe=timeframe,
                candles=cached,
                source="cache",
            )

        candles = self.download_ohlcv(symbol, timeframe, limit, downloader)
        self.cache.put(self.exchange, symbol, timeframe, candles)
        return HistoryLoadResult(
            symbol=symbol,
            exchange=self.exchange,
            timeframe=timeframe,
            candles=candles[-limit:],
            source="download",
        )

    def download_ohlcv(self, symbol: str, timeframe: str, limit: int, downloader: DownloadFn) -> list[Candle]:
        candles = downloader(symbol, timeframe, limit)
        if not candles:
            raise RuntimeError("history downloader returned no candles")
        return candles[-limit:]


class HistoryLoader:
    def __init__(self, engine: HistoricalMarketDataEngine) -> None:
        self.engine = engine

    def load(
        self,
        symbol: str,
        timeframe: str,
        limit: int,
        downloader: DownloadFn,
        force_refresh: bool = False,
    ) -> HistoryLoadResult:
        return self.engine.load_history(
            symbol,
            timeframe,
            limit,
            downloader,
            force_refresh=force_refresh,
        )
