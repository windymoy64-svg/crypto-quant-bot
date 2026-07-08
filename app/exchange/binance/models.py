from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class BinanceConfig:
    exchange: str = "binance"
    testnet: bool = True
    live_trading: bool = False
    recv_window: int = 5000
    timeout: int = 30

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "BinanceConfig":
        return cls(
            exchange=str(data.get("exchange", "binance")),
            testnet=_as_bool(data.get("testnet", True)),
            live_trading=_as_bool(data.get("live_trading", False)),
            recv_window=int(data.get("recv_window", 5000)),
            timeout=int(data.get("timeout", 30)),
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class BinanceTickerPrice:
    symbol: str
    price: float

    @classmethod
    def from_api(cls, row: dict[str, object]) -> "BinanceTickerPrice":
        return cls(symbol=str(row.get("symbol", "")), price=float(row.get("price") or 0.0))

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class BinanceBookTicker:
    symbol: str
    bid_price: float
    bid_qty: float
    ask_price: float
    ask_qty: float

    @classmethod
    def from_api(cls, row: dict[str, object]) -> "BinanceBookTicker":
        return cls(
            symbol=str(row.get("symbol", "")),
            bid_price=float(row.get("bidPrice") or 0.0),
            bid_qty=float(row.get("bidQty") or 0.0),
            ask_price=float(row.get("askPrice") or 0.0),
            ask_qty=float(row.get("askQty") or 0.0),
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class BinanceOrderBook:
    last_update_id: int
    bids: list[list[float]]
    asks: list[list[float]]

    @classmethod
    def from_api(cls, data: dict[str, object]) -> "BinanceOrderBook":
        return cls(
            last_update_id=int(data.get("lastUpdateId") or 0),
            bids=_price_levels(data.get("bids")),
            asks=_price_levels(data.get("asks")),
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _price_levels(value: object) -> list[list[float]]:
    if not isinstance(value, list):
        return []
    return [[float(level[0]), float(level[1])] for level in value if isinstance(level, list) and len(level) >= 2]


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}