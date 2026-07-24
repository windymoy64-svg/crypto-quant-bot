from __future__ import annotations

import json
import socket
from datetime import UTC, datetime
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.core.models import Candle
from app.exchange.base import ExchangeClient


class PublicHttpExchangeClient(ExchangeClient):
    def __init__(self, exchange_id: str = "binance", timeout_seconds: int = 10) -> None:
        self.exchange_id = exchange_id.lower()
        self.timeout_seconds = timeout_seconds
        socket.setdefaulttimeout(timeout_seconds)

    def fetch_candles(self, symbol: str, timeframe: str = "1m", limit: int = 100) -> list[Candle]:
        if self.exchange_id == "binance":
            return self._fetch_binance_candles(symbol, timeframe, limit)
        if self.exchange_id == "okx":
            return self._fetch_okx_candles(symbol, timeframe, limit)
        if self.exchange_id == "bitunix":
            return self._fetch_bitunix_candles(symbol, timeframe, limit)
        raise ValueError(f"Unsupported public HTTP exchange: {self.exchange_id}")

    def fetch_all_symbols(
        self,
        *,
        quote_asset: str = "USDT",
        only_trading: bool = True,
        spot_only: bool = True,
    ) -> list[str]:
        """Ambil semua simbol dari Binance secara dinamis.

        Coin baru otomatis muncul, coin yang delisting otomatis hilang,
        karena sumbernya langsung exchangeInfo.
        """
        if self.exchange_id != "binance":
            raise ValueError(f"fetch_all_symbols belum didukung untuk {self.exchange_id}")

        data = self._get_json("https://api.binance.com/api/v3/exchangeInfo", {})
        symbols: list[str] = []
        for row in data.get("symbols", []):
            if only_trading and row.get("status") != "TRADING":
                continue
            if quote_asset and row.get("quoteAsset") != quote_asset:
                continue
            if spot_only and not row.get("isSpotTradingAllowed", False):
                continue
            base = row.get("baseAsset")
            quote = row.get("quoteAsset")
            if base and quote:
                symbols.append(f"{base}/{quote}")
        return sorted(symbols)
    
    def fetch_top_symbols_by_volume(
        self,
        *,
        quote_asset: str = "USDT",
        top_n: int = 100,
        only_trading: bool = True,
    ) -> list[str]:
        """Ambil top-N simbol paling likuid berdasarkan quoteVolume 24h.

        Ini prefilter penting: menyaring coin dead/ilikuid, dan menghemat
        jumlah request klines saat scanning.
        """
        if self.exchange_id != "binance":
            raise ValueError(f"fetch_top_symbols_by_volume belum didukung untuk {self.exchange_id}")

        info = self._get_json("https://api.binance.com/api/v3/exchangeInfo", {})
        allowed: set[str] = set()
        for row in info.get("symbols", []):
            if only_trading and row.get("status") != "TRADING":
                continue
            if quote_asset and row.get("quoteAsset") != quote_asset:
                continue
            if not row.get("isSpotTradingAllowed", False):
                continue
            allowed.add(row.get("symbol", ""))

        tickers = self._get_json("https://api.binance.com/api/v3/ticker/24hr", {})
        rows: list[tuple[str, str, float]] = []
        for t in tickers if isinstance(tickers, list) else []:
            sym = t.get("symbol", "")
            if sym not in allowed:
                continue
            try:
                quote_vol = float(t.get("quoteVolume") or 0)
            except (TypeError, ValueError):
                quote_vol = 0.0
            if quote_vol <= 0:
                continue
            base = sym[: -len(quote_asset)] if sym.endswith(quote_asset) else sym
            rows.append((f"{base}/{quote_asset}", sym, quote_vol))

        rows.sort(key=lambda r: r[2], reverse=True)
        return [r[0] for r in rows[:top_n]]

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
        if self.exchange_id == "bitunix":
            data = self._get_json(
                "https://fapi.bitunix.com/api/v1/futures/market/tickers",
                {"symbols": self._bitunix_symbol(symbol)},
            )
            row = self._first_bitunix_row(data)
            last = float(row.get("lastPrice") or row.get("last") or row.get("markPrice") or 0)
            return {
                "symbol": symbol,
                "bid": last,
                "ask": last,
                "last": last,
                "volume": float(row.get("baseVol") or row.get("quoteVol") or 0),
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

    def _fetch_bitunix_candles(self, symbol: str, timeframe: str, limit: int) -> list[Candle]:
        payload = self._get_json(
            "https://fapi.bitunix.com/api/v1/futures/market/kline",
            {"symbol": self._bitunix_symbol(symbol), "interval": timeframe, "limit": limit},
        )
        if isinstance(payload, dict) and payload.get("code") != 0:
            raise ValueError(f"bitunix_error: {payload.get('msg', 'unknown')}")
        rows = payload.get("data", []) if isinstance(payload, dict) else []
        rows = sorted(rows, key=lambda row: int(float(row.get("time", 0))))[-limit:]
        return [
            Candle(
                symbol=symbol,
                timestamp=self._format_timestamp(row.get("time", 0)),
                open=float(row.get("open", 0)),
                high=float(row.get("high", 0)),
                low=float(row.get("low", 0)),
                close=float(row.get("close", 0)),
                volume=float(row.get("baseVol", row.get("volume", 0)) or 0),
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

    def _bitunix_symbol(self, symbol: str) -> str:
        return symbol.replace("/", "").replace("-", "").upper()

    def _first_bitunix_row(self, payload: object) -> dict[str, object]:
        rows = payload.get("data", []) if isinstance(payload, dict) else []
        if not isinstance(rows, list) or not rows:
            raise ValueError("bitunix returned no ticker data")
        row = rows[0]
        if not isinstance(row, dict):
            raise ValueError("invalid bitunix ticker payload")
        return row

    def _get_json(self, url: str, params: dict[str, str | int]) -> object:
        query = urlencode(params)
        full_url = f"{url}?{query}" if query else url
        try:
            headers = {}
            if "bitunix.com" in url:
                headers = {
                    "User-Agent": "crypto-quant-bot/1.0 (+public-market)",
                    "Accept": "application/json",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Referer": "https://www.bitunix.com/api-docs/",
                }
            request = Request(full_url, headers=headers)
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except (socket.timeout, URLError) as exc:
            # Return empty dict on timeout - caller handles it
            print(f"API timeout/error {url}: {exc}", flush=True)
            return {}

    def _format_timestamp(self, value: int | float | str) -> str:
        return datetime.fromtimestamp(float(value) / 1000, tz=UTC).isoformat()

    def _binance_symbol(self, symbol: str) -> str:
        return symbol.replace("/", "").replace("-", "").upper()

    def _okx_symbol(self, symbol: str) -> str:
        return symbol.replace("/", "-").upper()