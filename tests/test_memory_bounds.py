from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import Mock, patch

from app.core.models import Candle
from app.dashboard.services import iter_jsonl_file, read_json_file, read_jsonl_file
from app.dashboard.websocket import DashboardEventHub
from app.market.data_service import MarketDataService


def test_read_jsonl_file_keeps_latest_valid_rows(tmp_path: Path) -> None:
    path = tmp_path / "large.jsonl"
    with path.open("w", encoding="utf-8") as file:
        for index in range(1_000):
            file.write(json.dumps({"index": index}) + "\n")
        file.write("invalid json\n")
        file.write(json.dumps(["not", "an", "object"]) + "\n")

    rows = read_jsonl_file(path, limit=3)

    assert [row["index"] for row in rows] == [997, 998, 999]


def test_read_jsonl_file_unbounded_preserves_all_valid_rows(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text('{"index": 1}\ninvalid\n{"index": 2}\n', encoding="utf-8")

    assert read_jsonl_file(path, limit=None) == [{"index": 1}, {"index": 2}]
    assert read_jsonl_file(path, limit=0) == [{"index": 1}, {"index": 2}]
    assert list(iter_jsonl_file(path)) == [{"index": 1}, {"index": 2}]


def test_read_json_file_returns_default_for_io_error(tmp_path: Path) -> None:
    path = tmp_path / "payload.json"
    path.write_text('{"ok": true}', encoding="utf-8")

    with patch.object(Path, "open", side_effect=OSError("unavailable")):
        assert read_json_file(path, {"fallback": True}) == {"fallback": True}


def test_market_data_service_reuses_one_ccxt_client() -> None:
    service = MarketDataService(exchange="binance")
    fake_client = object()

    with patch(
        "app.market.data_service.CcxtExchangeClient",
        return_value=fake_client,
    ) as client_type:
        assert service._get_ccxt_client() is fake_client
        assert service._get_ccxt_client() is fake_client

    client_type.assert_called_once_with("binance")


def test_binance_public_connector_avoids_loading_ccxt() -> None:
    service = MarketDataService(exchange="binance")
    candle = Candle(
        symbol="BTC/USDT",
        timestamp="2026-01-01T00:00:00+00:00",
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        volume=10.0,
    )
    connector = Mock()
    connector.fetch_candles.return_value = [candle]

    with patch(
        "app.market.data_service.BinanceConnector",
        return_value=connector,
    ), patch("app.market.data_service.CcxtExchangeClient") as ccxt_type:
        result = service._fetch_ohlcv_without_cache("BTC/USDT", "1m", 1)

    assert result.candles == [candle]
    assert result.source == "binance_connector"
    ccxt_type.assert_not_called()


def test_market_data_service_reuses_one_binance_connector() -> None:
    service = MarketDataService(exchange="binance")
    connector = Mock()

    with patch(
        "app.market.data_service.BinanceConnector",
        return_value=connector,
    ) as connector_type:
        assert service._get_binance_client() is connector
        assert service._get_binance_client() is connector

    connector_type.assert_called_once_with()


def test_dashboard_event_queue_drops_oldest_when_full() -> None:
    hub = DashboardEventHub(max_pending_events=2)
    hub._queue = asyncio.Queue(maxsize=2)

    hub._enqueue_latest({"id": 1})
    hub._enqueue_latest({"id": 2})
    hub._enqueue_latest({"id": 3})

    assert hub._queue.qsize() == 2
    assert hub._queue.get_nowait() == {"id": 2}
    assert hub._queue.get_nowait() == {"id": 3}