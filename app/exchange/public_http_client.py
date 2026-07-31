from __future__ import annotations

import json
import socket
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.core.models import Candle
from app.exchange.base import ExchangeClient


@dataclass(frozen=True)
class TickerSnapshot:
    """24h ticker fields used for universe prefilter and market context."""

    symbol: str
    market_symbol: str
    last_price: float
    change_24h_pct: float
    vol_coin_24h: float
    vol_usdt_24h: float
    trade_count_24h: int = 0

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def liquidity_quality(
        self,
        *,
        high_usdt: float = 50_000_000.0,
        med_usdt: float = 10_000_000.0,
    ) -> str:
        if self.vol_usdt_24h >= high_usdt:
            return "high"
        if self.vol_usdt_24h >= med_usdt:
            return "med"
        if self.vol_usdt_24h > 0:
            return "low"
        return "none"


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
        """Ambil semua simbol dari Binance secara dinamis."""
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

    def fetch_24h_ticker_snapshots(
        self,
        *,
        quote_asset: str = "USDT",
        only_trading: bool = True,
        min_quote_volume_usdt: float = 0.0,
        excluded_base_assets: set[str] | frozenset[str] | None = None,
    ) -> list[TickerSnapshot]:
        """Ambil snapshot 24h (price, % change, dual volume) untuk prefilter."""
        if self.exchange_id == "bitunix":
            return self._fetch_bitunix_24h_ticker_snapshots(
                quote_asset=quote_asset,
                min_quote_volume_usdt=min_quote_volume_usdt,
                excluded_base_assets=excluded_base_assets,
            )
        if self.exchange_id != "binance":
            raise ValueError(
                f"fetch_24h_ticker_snapshots belum didukung untuk {self.exchange_id}"
            )

        info = self._get_json("https://api.binance.com/api/v3/exchangeInfo", {})
        allowed: set[str] = set()
        for row in info.get("symbols", []):
            if only_trading and row.get("status") != "TRADING":
                continue
            if quote_asset and row.get("quoteAsset") != quote_asset:
                continue
            if not row.get("isSpotTradingAllowed", False):
                continue
            allowed.add(str(row.get("symbol", "")))

        excluded = {
            str(value).strip().upper()
            for value in (excluded_base_assets or set())
            if str(value).strip()
        }

        tickers = self._get_json("https://api.binance.com/api/v3/ticker/24hr", {})
        snapshots: list[TickerSnapshot] = []
        for row in tickers if isinstance(tickers, list) else []:
            market_symbol = str(row.get("symbol", ""))
            if market_symbol not in allowed:
                continue
            if not market_symbol.endswith(quote_asset):
                continue
            base = market_symbol[: -len(quote_asset)]
            if base.upper() in excluded:
                continue
            try:
                quote_vol = float(row.get("quoteVolume") or 0)
            except (TypeError, ValueError):
                quote_vol = 0.0
            if quote_vol <= 0:
                continue
            if min_quote_volume_usdt > 0 and quote_vol < min_quote_volume_usdt:
                continue
            try:
                last_price = float(row.get("lastPrice") or 0)
            except (TypeError, ValueError):
                last_price = 0.0
            try:
                change_pct = float(row.get("priceChangePercent") or 0)
            except (TypeError, ValueError):
                change_pct = 0.0
            try:
                vol_coin = float(row.get("volume") or 0)
            except (TypeError, ValueError):
                vol_coin = 0.0
            try:
                trade_count = int(float(row.get("count") or 0))
            except (TypeError, ValueError):
                trade_count = 0

            snapshots.append(
                TickerSnapshot(
                    symbol=f"{base}/{quote_asset}",
                    market_symbol=market_symbol,
                    last_price=last_price,
                    change_24h_pct=change_pct,
                    vol_coin_24h=vol_coin,
                    vol_usdt_24h=quote_vol,
                    trade_count_24h=trade_count,
                )
            )
        return snapshots

    def _fetch_bitunix_24h_ticker_snapshots(
        self,
        *,
        quote_asset: str,
        min_quote_volume_usdt: float,
        excluded_base_assets: set[str] | frozenset[str] | None,
    ) -> list[TickerSnapshot]:
        """Parse the public Bitunix futures ticker collection.

        Bitunix has used both ``data: []`` and nested list payloads, and field
        names differ slightly between API revisions. Keep this read-only parser
        tolerant so a harmless response change does not disable scanner breadth.
        """

        payload = self._get_json(
            "https://fapi.bitunix.com/api/v1/futures/market/tickers", {}
        )
        if isinstance(payload, dict) and payload.get("code") not in (None, 0):
            raise ValueError(f"bitunix_error: {payload.get('msg', 'unknown')}")
        data = payload.get("data", []) if isinstance(payload, dict) else payload
        if isinstance(data, dict):
            rows = next(
                (data.get(key) for key in ("tickerList", "list", "rows") if isinstance(data.get(key), list)),
                [],
            )
        else:
            rows = data if isinstance(data, list) else []

        quote = quote_asset.upper()
        excluded = {str(value).strip().upper() for value in (excluded_base_assets or set())}
        snapshots: list[TickerSnapshot] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            market_symbol = str(row.get("symbol") or row.get("s") or "").upper()
            if not market_symbol.endswith(quote) or len(market_symbol) <= len(quote):
                continue
            base = market_symbol[:-len(quote)]
            if base in excluded:
                continue
            try:
                last_price = float(row.get("lastPrice") or row.get("last") or row.get("markPrice") or 0)
                change_pct = float(
                    row.get("priceChangePercent")
                    or row.get("change24h")
                    or row.get("changeRate")
                    or row.get("priceChangeRate")
                    or 0
                )
                # Some revisions expose changeRate as a ratio (0.05 = 5%).
                if abs(change_pct) <= 1 and any(
                    key in row for key in ("changeRate", "priceChangeRate")
                ):
                    change_pct *= 100
                if not any(
                    key in row
                    for key in ("priceChangePercent", "change24h", "changeRate", "priceChangeRate")
                ):
                    open_price = float(row.get("open") or 0)
                    if open_price > 0:
                        change_pct = ((last_price - open_price) / open_price) * 100
                vol_coin = float(row.get("baseVol") or row.get("volume") or 0)
                quote_vol = float(
                    row.get("quoteVol") or row.get("quoteVolume") or row.get("turnover") or 0
                )
                if quote_vol <= 0 and vol_coin > 0 and last_price > 0:
                    quote_vol = vol_coin * last_price
                trade_count = int(float(row.get("tradeCount") or row.get("count") or 0))
            except (TypeError, ValueError):
                continue
            if last_price <= 0 or quote_vol <= 0:
                continue
            if min_quote_volume_usdt > 0 and quote_vol < min_quote_volume_usdt:
                continue
            snapshots.append(TickerSnapshot(
                symbol=f"{base}/{quote}",
                market_symbol=market_symbol,
                last_price=last_price,
                change_24h_pct=change_pct,
                vol_coin_24h=vol_coin,
                vol_usdt_24h=quote_vol,
                trade_count_24h=trade_count,
            ))
        return snapshots

    def fetch_bitunix_trading_pairs(self) -> list[dict[str, object]]:
        """Return official Bitunix pair metadata including OpenAPI support."""

        if self.exchange_id != "bitunix":
            raise ValueError("Bitunix trading-pair metadata requires exchange_id=bitunix")
        payload = self._get_json(
            "https://fapi.bitunix.com/api/v1/futures/market/trading_pairs", {}
        )
        if not isinstance(payload, dict) or payload.get("code") != 0:
            message = payload.get("msg") if isinstance(payload, dict) else "invalid response"
            raise ValueError(f"bitunix_trading_pairs_error: {message}")
        rows = payload.get("data", [])
        return [dict(row) for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


    def prefilter_symbols(
        self,
        *,
        quote_asset: str = "USDT",
        top_n: int = 100,
        only_trading: bool = True,
        min_quote_volume_usdt: float = 0.0,
        min_move_pct: float = 0.0,
        mode: str = "top_volume",
        momentum_sort: str = "quote_volume",
        excluded_base_assets: set[str] | frozenset[str] | None = None,
    ) -> tuple[list[str], list[TickerSnapshot], dict[str, TickerSnapshot]]:
        """Prefilter universe dari ticker 24h.

        Modes:
          - top_volume: sort quoteVolume desc
          - top_gainer: sort change_24h_pct desc
          - top_loser: sort change_24h_pct asc
          - momentum_liquid: |change| >= min_move_pct, then sort by momentum_sort
        """
        snapshots = self.fetch_24h_ticker_snapshots(
            quote_asset=quote_asset,
            only_trading=only_trading,
            min_quote_volume_usdt=min_quote_volume_usdt,
            excluded_base_assets=excluded_base_assets,
        )
        if not snapshots:
            return [], [], {}

        mode_key = str(mode or "top_volume").strip().lower()
        rows = list(snapshots)

        if mode_key == "top_gainer":
            rows.sort(key=lambda item: item.change_24h_pct, reverse=True)
        elif mode_key == "top_loser":
            rows.sort(key=lambda item: item.change_24h_pct)
        elif mode_key == "momentum_liquid":
            move_floor = float(min_move_pct or 0.0)
            sort_key = str(momentum_sort or "quote_volume").strip().lower()

            def _sort_key(item: TickerSnapshot) -> float:
                if sort_key == "abs_change":
                    return abs(item.change_24h_pct)
                return item.vol_usdt_24h

            # Prefer movers, then pad with liquid non-movers so top_n stays full.
            if move_floor > 0:
                movers = [item for item in rows if abs(item.change_24h_pct) >= move_floor]
                rest = [item for item in rows if abs(item.change_24h_pct) < move_floor]
                movers.sort(key=_sort_key, reverse=True)
                rest.sort(key=_sort_key, reverse=True)
                rows = movers + rest
            else:
                rows.sort(key=_sort_key, reverse=True)
        else:
            rows.sort(key=lambda item: item.vol_usdt_24h, reverse=True)

        selected = rows[: max(0, int(top_n))] if top_n > 0 else rows
        symbols = [item.symbol for item in selected]
        by_symbol = {item.symbol: item for item in selected}
        return symbols, snapshots, by_symbol

    def fetch_top_symbols_by_volume(
        self,
        *,
        quote_asset: str = "USDT",
        top_n: int = 100,
        only_trading: bool = True,
        min_quote_volume_usdt: float = 0.0,
        excluded_base_assets: set[str] | frozenset[str] | None = None,
    ) -> list[str]:
        """Ambil top-N simbol paling likuid berdasarkan quoteVolume 24h."""
        symbols, _, _ = self.prefilter_symbols(
            quote_asset=quote_asset,
            top_n=top_n,
            only_trading=only_trading,
            min_quote_volume_usdt=min_quote_volume_usdt,
            mode="top_volume",
            excluded_base_assets=excluded_base_assets,
        )
        return symbols


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
                "change_24h_pct": float(data.get("priceChangePercent") or 0),
                "quote_volume": float(data.get("quoteVolume") or 0),
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
            print(f"API timeout/error {url}: {exc}", flush=True)
            return {}

    def _format_timestamp(self, value: int | float | str) -> str:
        return datetime.fromtimestamp(float(value) / 1000, tz=UTC).isoformat()

    def _binance_symbol(self, symbol: str) -> str:
        return symbol.replace("/", "").replace("-", "").upper()

    def _okx_symbol(self, symbol: str) -> str:
        return symbol.replace("/", "-").upper()

