from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.models import Candle
from app.dashboard.app import create_app
from app.dashboard.services import DashboardService
from app.market.data_service import MarketDataResult


def _fake_candles(symbol: str = "BTC/USDT", count: int = 5) -> list[Candle]:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    candles: list[Candle] = []
    for index in range(count):
        timestamp = (base + timedelta(hours=index)).isoformat()
        open_price = 100.0 + index
        close_price = open_price + (0.5 if index % 2 == 0 else -0.5)
        high_price = max(open_price, close_price) + 1.0
        low_price = min(open_price, close_price) - 1.0
        candles.append(
            Candle(
                symbol=symbol,
                timestamp=timestamp,
                open=open_price,
                high=high_price,
                low=low_price,
                close=close_price,
                volume=10.0 + index,
            )
        )
    return candles


def _fake_result(**overrides: object) -> MarketDataResult:
    defaults: dict[str, object] = {
        "symbol": "BTC/USDT",
        "timeframe": "1h",
        "candles": _fake_candles(),
        "source": "unit-test",
        "warning": None,
    }
    defaults.update(overrides)
    return MarketDataResult(**defaults)  # type: ignore[arg-type]


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.delenv("BOT_API_KEY", raising=False)
    return TestClient(create_app())


def test_service_klines_returns_normalized_candles() -> None:
    service = DashboardService()

    with patch(
        "app.dashboard.services.MarketDataService.fetch_ohlcv",
        return_value=_fake_result(),
    ) as fetch:
        payload = service.klines(symbol="btc-usdt", timeframe="1h", limit=5)

    fetch.assert_called_once_with(symbol="BTC/USDT", timeframe="1h", limit=5)
    assert payload["symbol"] == "BTC/USDT"
    assert payload["timeframe"] == "1h"
    assert payload["limit"] == 5
    assert payload["source"] == "unit-test"
    assert payload["read_only"] is True
    assert payload["count"] == 5
    first_candle = payload["candles"][0]
    assert set(first_candle.keys()) >= {
        "symbol",
        "timestamp",
        "time",
        "open",
        "high",
        "low",
        "close",
        "volume",
    }
    assert first_candle["time"] > 0
    assert first_candle["open"] > 0
    assert first_candle["close"] > 0


def test_service_klines_defaults_and_clamps() -> None:
    service = DashboardService()

    with patch(
        "app.dashboard.services.MarketDataService.fetch_ohlcv",
        return_value=_fake_result(),
    ) as fetch:
        service.klines(symbol="", timeframe="bogus", limit=-10)

    fetch.assert_called_once_with(symbol="BTC/USDT", timeframe="1h", limit=200)


def test_service_klines_handles_downstream_errors() -> None:
    service = DashboardService()

    with patch(
        "app.dashboard.services.MarketDataService.fetch_ohlcv",
        side_effect=RuntimeError("network down"),
    ):
        payload = service.klines(symbol="ETH/USDT", timeframe="5m", limit=10)

    assert payload["source"] == "error"
    assert payload["candles"] == []
    assert payload["count"] == 0
    assert "network down" in str(payload["warning"])


def test_api_klines_endpoint_returns_candles(client: TestClient) -> None:
    with patch(
        "app.dashboard.services.MarketDataService.fetch_ohlcv",
        return_value=_fake_result(),
    ):
        response = client.get(
            "/api/klines",
            params={"symbol": "BTC/USDT", "timeframe": "1h", "limit": 5},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "BTC/USDT"
    assert body["timeframe"] == "1h"
    assert body["count"] == 5
    assert body["read_only"] is True
    assert len(body["candles"]) == 5


def test_api_klines_endpoint_rejects_invalid_limit(client: TestClient) -> None:
    response = client.get(
        "/api/klines",
        params={"symbol": "BTC/USDT", "timeframe": "1h", "limit": 5000},
    )
    assert response.status_code == 422
