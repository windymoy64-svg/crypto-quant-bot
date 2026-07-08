from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BinanceSubscription:
    symbols: list[str] = field(default_factory=list)
    streams: list[str] = field(default_factory=list)

    @classmethod
    def for_market_data(
        cls,
        symbols: list[str],
        *,
        interval: str = "1m",
        include_kline: bool = True,
        include_mini_ticker: bool = True,
        include_book_ticker: bool = True,
        include_depth: bool = False,
        include_agg_trade: bool = False,
    ) -> "BinanceSubscription":
        normalized = [normalize_symbol(symbol) for symbol in symbols]
        streams: list[str] = []
        for symbol in normalized:
            if include_kline:
                streams.append(kline_stream(symbol, interval))
            if include_mini_ticker:
                streams.append(mini_ticker_stream(symbol))
            if include_book_ticker:
                streams.append(book_ticker_stream(symbol))
            if include_depth:
                streams.append(depth_stream(symbol))
            if include_agg_trade:
                streams.append(agg_trade_stream(symbol))
        return cls(symbols=normalized, streams=streams)

    def combined_path(self) -> str:
        return "/stream?streams=" + "/".join(self.streams)

    def is_empty(self) -> bool:
        return not self.streams


def normalize_symbol(symbol: str) -> str:
    return symbol.replace("/", "").replace("-", "").lower()


def kline_stream(symbol: str, interval: str = "1m") -> str:
    return f"{normalize_symbol(symbol)}@kline_{interval}"


def mini_ticker_stream(symbol: str) -> str:
    return f"{normalize_symbol(symbol)}@miniTicker"


def book_ticker_stream(symbol: str) -> str:
    return f"{normalize_symbol(symbol)}@bookTicker"


def depth_stream(symbol: str, levels: int = 20, speed_ms: int = 100) -> str:
    return f"{normalize_symbol(symbol)}@depth{levels}@{speed_ms}ms"


def agg_trade_stream(symbol: str) -> str:
    return f"{normalize_symbol(symbol)}@aggTrade"