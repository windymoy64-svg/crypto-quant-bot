from __future__ import annotations

from typing import Any

import pytest

from app.exchange.binance_futures.client import FuturesHttpResponse
from app.exchange.binance_futures.exchange_info import (
    FuturesExchangeInfoReader,
    FuturesSymbolInfo,
)


class _StubClient:
    def __init__(self, body: Any) -> None:
        self._body = body
        self.calls: list[tuple[str, dict[str, Any] | None, bool]] = []

    def get(self, path, params=None, *, signed=True):
        self.calls.append((path, dict(params or {}) if params else None, signed))
        return FuturesHttpResponse(status_code=200, body=self._body)


_EXCHANGE_INFO = {
    "timezone": "UTC",
    "serverTime": 1_700_000_000_000,
    "symbols": [
        {
            "symbol": "BTCUSDT",
            "status": "TRADING",
            "contractType": "PERPETUAL",
            "baseAsset": "BTC",
            "quoteAsset": "USDT",
            "marginAsset": "USDT",
            "pricePrecision": 2,
            "quantityPrecision": 3,
            "orderTypes": ["LIMIT", "MARKET", "STOP", "STOP_MARKET"],
            "filters": [
                {"filterType": "PRICE_FILTER", "tickSize": "0.10"},
                {
                    "filterType": "LOT_SIZE",
                    "stepSize": "0.001",
                    "minQty": "0.001",
                    "maxQty": "1000",
                },
                {"filterType": "MARKET_LOT_SIZE", "stepSize": "0.001"},
                {"filterType": "MIN_NOTIONAL", "notional": "5"},
            ],
        },
        {
            "symbol": "ETHUSDT",
            "status": "TRADING",
            "contractType": "PERPETUAL",
            "baseAsset": "ETH",
            "quoteAsset": "USDT",
            "marginAsset": "USDT",
            "pricePrecision": 2,
            "quantityPrecision": 3,
            "orderTypes": ["LIMIT", "MARKET"],
            "filters": [
                {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                {
                    "filterType": "LOT_SIZE",
                    "stepSize": "0.001",
                    "minQty": "0.001",
                    "maxQty": "10000",
                },
                {"filterType": "MIN_NOTIONAL", "notional": "5"},
            ],
        },
    ],
}


def test_get_parses_symbol_filters() -> None:
    stub = _StubClient(_EXCHANGE_INFO)
    reader = FuturesExchangeInfoReader(stub)

    info = reader.get("btcusdt")

    assert stub.calls[0] == ("/fapi/v1/exchangeInfo", None, False)
    assert info.symbol == "BTCUSDT"
    assert info.status == "TRADING"
    assert info.is_perpetual is True
    assert info.is_trading is True
    assert info.tick_size == pytest.approx(0.10)
    assert info.step_size == pytest.approx(0.001)
    assert info.market_step_size == pytest.approx(0.001)
    assert info.min_qty == pytest.approx(0.001)
    assert info.max_qty == pytest.approx(1000.0)
    assert info.min_notional == pytest.approx(5.0)
    assert "MARKET" in info.order_types


def test_get_caches_between_calls() -> None:
    stub = _StubClient(_EXCHANGE_INFO)
    reader = FuturesExchangeInfoReader(stub)

    reader.get("BTCUSDT")
    reader.get("ETHUSDT")

    assert len(stub.calls) == 1


def test_get_refresh_refetches() -> None:
    stub = _StubClient(_EXCHANGE_INFO)
    reader = FuturesExchangeInfoReader(stub)

    reader.get("BTCUSDT")
    reader.get("BTCUSDT", refresh=True)

    assert len(stub.calls) == 2


def test_get_unknown_symbol_raises() -> None:
    reader = FuturesExchangeInfoReader(_StubClient(_EXCHANGE_INFO))

    with pytest.raises(KeyError):
        reader.get("UNKNOWN")


def test_all_returns_every_symbol() -> None:
    reader = FuturesExchangeInfoReader(_StubClient(_EXCHANGE_INFO))

    all_info = reader.all()

    assert set(all_info.keys()) == {"BTCUSDT", "ETHUSDT"}


def test_missing_filters_fall_back_to_zero() -> None:
    body = {
        "symbols": [
            {
                "symbol": "MISSING",
                "status": "BREAK",
                "contractType": "PERPETUAL",
                "baseAsset": "MIS",
                "quoteAsset": "USDT",
                "filters": [],
            }
        ]
    }
    reader = FuturesExchangeInfoReader(_StubClient(body))

    info = reader.get("MISSING")

    assert info.tick_size == 0.0
    assert info.step_size == 0.0
    assert info.min_notional == 0.0
    assert info.is_trading is False


def test_exchange_info_uses_public_endpoint() -> None:
    stub = _StubClient(_EXCHANGE_INFO)
    reader = FuturesExchangeInfoReader(stub)

    reader.refresh()

    # signed=False so it works without API credentials.
    assert stub.calls[0][2] is False
