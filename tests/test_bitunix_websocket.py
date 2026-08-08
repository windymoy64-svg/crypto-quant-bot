from __future__ import annotations

from app.market.bitunix_websocket import BitunixTickerWebSocket


def test_parse_bitunix_ticker_payload() -> None:
    result = BitunixTickerWebSocket.parse_ticker({
        "data": {"symbol": "BTCUSDT", "lastPrice": "65000.5", "ts": 1700000000000},
    })

    assert result == {
        "symbol": "BTC/USDT",
        "price": 65000.5,
        "timestamp": 1700000000000,
    }


def test_parse_bitunix_ticker_accepts_nested_rows() -> None:
    result = BitunixTickerWebSocket.parse_ticker({
        "data": [{"symbol": "ETH-USDT", "markPrice": "3000"}],
    })

    assert result == {"symbol": "ETH/USDT", "price": 3000.0, "timestamp": 0}


def test_parse_bitunix_ticker_rejects_invalid_payload() -> None:
    assert BitunixTickerWebSocket.parse_ticker({"data": {"symbol": "BTCUSDT"}}) is None
