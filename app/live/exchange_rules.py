from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.request import urlopen


BINANCE_EXCHANGE_INFO_URL = "https://api.binance.com/api/v3/exchangeInfo"
SUPPORTED_FILTERS = {
    "PRICE_FILTER",
    "LOT_SIZE",
    "MIN_NOTIONAL",
    "NOTIONAL",
    "MARKET_LOT_SIZE",
    "MAX_NUM_ORDERS",
}


@dataclass(frozen=True)
class ExchangeSymbolRules:
    symbol: str
    status: str
    baseAsset: str
    quoteAsset: str
    basePrecision: int
    quotePrecision: int
    orderTypes: list[str]
    permissions: list[str]
    filters: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def from_binance(cls, data: dict[str, Any]) -> "ExchangeSymbolRules":
        filters = {
            item["filterType"]: dict(item)
            for item in data.get("filters", [])
            if isinstance(item, dict) and item.get("filterType") in SUPPORTED_FILTERS
        }
        return cls(
            symbol=str(data.get("symbol", "")).upper(),
            status=str(data.get("status", "")),
            baseAsset=str(data.get("baseAsset", "")),
            quoteAsset=str(data.get("quoteAsset", "")),
            basePrecision=int(data.get("baseAssetPrecision", data.get("basePrecision", 0))),
            quotePrecision=int(data.get("quoteAssetPrecision", data.get("quotePrecision", 0))),
            orderTypes=[str(value) for value in data.get("orderTypes", [])],
            permissions=[str(value) for value in data.get("permissions", [])],
            filters=filters,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExchangeSymbolRules":
        return cls(
            symbol=str(data.get("symbol", "")).upper(),
            status=str(data.get("status", "")),
            baseAsset=str(data.get("baseAsset", "")),
            quoteAsset=str(data.get("quoteAsset", "")),
            basePrecision=int(data.get("basePrecision", 0)),
            quotePrecision=int(data.get("quotePrecision", 0)),
            orderTypes=[str(value) for value in data.get("orderTypes", [])],
            permissions=[str(value) for value in data.get("permissions", [])],
            filters={str(key): dict(value) for key, value in data.get("filters", {}).items()},
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExchangeInfo:
    symbols: dict[str, ExchangeSymbolRules]

    @classmethod
    def from_binance(cls, data: dict[str, Any]) -> "ExchangeInfo":
        symbols = {}
        for item in data.get("symbols", []):
            if isinstance(item, dict):
                rules = ExchangeSymbolRules.from_binance(item)
                if rules.symbol:
                    symbols[rules.symbol] = rules
        return cls(symbols=symbols)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExchangeInfo":
        return cls(
            symbols={
                str(symbol).upper(): ExchangeSymbolRules.from_dict(payload)
                for symbol, payload in data.get("symbols", {}).items()
                if isinstance(payload, dict)
            }
        )

    def get_symbol(self, symbol: str) -> ExchangeSymbolRules | None:
        return self.symbols.get(normalize_symbol(symbol))

    def to_dict(self) -> dict[str, Any]:
        return {"symbols": {symbol: rules.to_dict() for symbol, rules in self.symbols.items()}}


class BinanceExchangeInfoLoader:
    def __init__(self, url: str = BINANCE_EXCHANGE_INFO_URL, timeout: float = 10.0) -> None:
        self.url = url
        self.timeout = timeout

    def fetch(self) -> ExchangeInfo:
        with urlopen(self.url, timeout=self.timeout) as response:  # nosec B310 - read-only public endpoint
            payload = json.loads(response.read().decode("utf-8"))
        return ExchangeInfo.from_binance(payload)


def normalize_symbol(symbol: str) -> str:
    return symbol.replace("/", "").replace("-", "").upper()