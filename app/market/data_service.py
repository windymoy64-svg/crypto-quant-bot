from __future__ import annotations

from dataclasses import dataclass

from app.core.models import Candle
from app.events.events import PriceUpdated
from app.events.publisher import publish
from app.exchange.binance import BinanceConnector
from app.exchange.binance.stream import BinanceStreamCallbacks
from app.exchange.binance.websocket import BinanceWebSocket
from app.exchange.ccxt_client import CcxtExchangeClient
from app.exchange.public_http_client import PublicHttpExchangeClient
from app.market.history import HistoricalMarketDataEngine, HistoryLoader
from app.market.sample_data import load_sample_candles


@dataclass(frozen=True)
class MarketDataResult:
    symbol: str
    timeframe: str
    candles: list[Candle]
    source: str
    warning: str | None = None


class MarketDataService:
    def __init__(self, exchange: str = "binance", *, fallback_to_sample_data: bool = True) -> None:
        self.exchange = exchange
        self.fallback_to_sample_data = fallback_to_sample_data
        self.history_loader = HistoryLoader(HistoricalMarketDataEngine(exchange=exchange))

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 100,
        *,
        force_refresh: bool = False,
    ) -> MarketDataResult:
        errors: list[str] = []

        try:
            history = self.history_loader.load(
                symbol,
                timeframe,
                limit,
                self._download_ohlcv,
                force_refresh=force_refresh,
            )

            return MarketDataResult(
                symbol=symbol,
                timeframe=timeframe,
                candles=history.candles,
                source=history.source,
                warning=history.warning,
            )
        except Exception as exc:
            errors.append(f"history: {exc}")

        return self._fetch_ohlcv_without_cache(symbol, timeframe, limit, errors)

    def _download_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list[Candle]:
        result = self._fetch_ohlcv_without_cache(symbol, timeframe, limit, [])
        return result.candles

    def _fetch_ohlcv_without_cache(
        self,
        symbol: str,
        timeframe: str,
        limit: int,
        errors: list[str] | None = None,
    ) -> MarketDataResult:
        errors = errors if errors is not None else []

        try:
            candles = CcxtExchangeClient(self.exchange).fetch_candles(symbol, timeframe=timeframe, limit=limit)
            if not candles:
                raise RuntimeError("ccxt returned no candles")
            return MarketDataResult(symbol=symbol, timeframe=timeframe, candles=candles, source="ccxt")
        except Exception as exc:
            errors.append(f"ccxt: {exc}")

        if self.exchange.lower() == "binance":
            try:
                candles = BinanceConnector().fetch_candles(symbol, timeframe=timeframe, limit=limit)
                if not candles:
                    raise RuntimeError("binance connector returned no candles")
                return MarketDataResult(
                    symbol=symbol,
                    timeframe=timeframe,
                    candles=candles,
                    source="binance_connector",
                    warning="; ".join(errors) if errors else None,
                )
            except Exception as exc:
                errors.append(f"binance_connector: {exc}")

        try:
            candles = PublicHttpExchangeClient(self.exchange).fetch_candles(
                symbol,
                timeframe=timeframe,
                limit=limit,
            )
            if not candles:
                raise RuntimeError("public API returned no candles")
            return MarketDataResult(
                symbol=symbol,
                timeframe=timeframe,
                candles=candles,
                source="binance_public_api",
                warning="; ".join(errors) if errors else None,
            )
        except Exception as exc:
            errors.append(f"public_api: {exc}")

        if not self.fallback_to_sample_data:
            raise RuntimeError("; ".join(errors))

        return MarketDataResult(
            symbol=symbol,
            timeframe=timeframe,
            candles=load_sample_candles(symbol)[-limit:],
            source="sample",
            warning=f"market data unavailable: {'; '.join(errors)}",
        )

    def fetch_ticker(self, symbol: str) -> dict[str, float | str]:
        errors: list[str] = []

        try:
            ticker = CcxtExchangeClient(self.exchange).fetch_ticker(symbol)
            self._publish_price_update(symbol, ticker, "ccxt")
            return ticker
        except Exception as exc:
            errors.append(f"ccxt: {exc}")

        if self.exchange.lower() == "binance":
            try:
                ticker = BinanceConnector().fetch_ticker(symbol)
                self._publish_price_update(symbol, ticker, "binance_connector")
                return ticker
            except Exception as exc:
                errors.append(f"binance_connector: {exc}")

        try:
            ticker = PublicHttpExchangeClient(self.exchange).fetch_ticker(symbol)
            self._publish_price_update(symbol, ticker, "public_api")
            return ticker
        except Exception as exc:
            errors.append(f"public_api: {exc}")

        if not self.fallback_to_sample_data:
            raise RuntimeError("; ".join(errors))

        candles = load_sample_candles(symbol)
        ticker = {
            "symbol": symbol,
            "bid": candles[-1].close,
            "ask": candles[-1].close,
            "last": candles[-1].close,
            "volume": candles[-1].volume,
        }
        self._publish_price_update(symbol, ticker, "sample")
        return ticker

    def fetch_last_price(self, symbol: str) -> float:
        ticker = self.fetch_ticker(symbol)
        return float(ticker.get("last") or ticker.get("ask") or ticker.get("bid") or 0.0)

    def fetch_volume(self, symbol: str, timeframe: str = "1h", limit: int = 100) -> float:
        result = self.fetch_ohlcv(symbol=symbol, timeframe=timeframe, limit=limit)
        return float(sum(candle.volume for candle in result.candles))

    def create_realtime_stream(
        self,
        symbols: list[str],
        *,
        timeframe: str = "1m",
        callbacks: BinanceStreamCallbacks | None = None,
        include_depth: bool = False,
        include_agg_trade: bool = False,
    ) -> BinanceWebSocket:
        if self.exchange.lower() != "binance":
            raise ValueError("Realtime websocket stream is currently supported only for Binance")
        stream = BinanceWebSocket(callbacks=callbacks)
        stream.subscribe_market_data(
            symbols,
            interval=timeframe,
            include_depth=include_depth,
            include_agg_trade=include_agg_trade,
        )
        return stream

    def _publish_price_update(self, symbol: str, ticker: dict[str, float | str], source: str) -> None:
        price = float(ticker.get("last") or ticker.get("ask") or ticker.get("bid") or 0.0)
        if price > 0:
            publish(PriceUpdated(symbol=str(ticker.get("symbol") or symbol), price=price, source=source))