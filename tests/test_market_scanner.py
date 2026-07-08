from app.core.models import Candle
from app.exchange.public_http_client import PublicHttpExchangeClient
from app.market.live_data import load_market_candles
from app.market.scanner import scan_symbols


class FakeExchangeClient:
    def fetch_candles(self, symbol: str, timeframe: str, limit: int) -> list[Candle]:
        return [
            Candle(symbol, "2026-07-06T00:00:00Z", 100, 101, 99, 100, 1000),
            Candle(symbol, "2026-07-06T00:01:00Z", 100, 102, 99, 101, 1100),
        ]

    def fetch_ticker(self, symbol: str) -> dict[str, float | str]:
        return {"symbol": symbol, "bid": 100.0, "ask": 101.0, "last": 100.5}


def test_load_market_candles_uses_live_client() -> None:
    loaded = load_market_candles(
        symbol="BTC/USDT",
        exchange="binance",
        timeframe="1m",
        limit=2,
        client=FakeExchangeClient(),
    )

    assert loaded.source == "live"
    assert loaded.candles[-1].close == 101


def test_scan_symbols_returns_json_ready_items() -> None:
    config = {
        "exchange": "binance",
        "timeframe": "1m",
        "limit": 100,
        "symbols": ["BTC/USDT"],
        "fallback_to_sample_data": True,
    }

    results = scan_symbols(config)

    assert results
    assert results[0].to_dict()["symbol"] == "BTC/USDT"


def test_public_http_client_formats_symbols() -> None:
    client = PublicHttpExchangeClient("binance")

    assert client._binance_symbol("BTC/USDT") == "BTCUSDT"
    assert client._okx_symbol("BTC/USDT") == "BTC-USDT"
