"""Unit tests for Ops MCP guards and read-only tools."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.mcp.guards import McpGuardError, resolve_project_path, scrub_secrets
from app.mcp import tools as ops_tools


def test_guard_allows_logs_path() -> None:
    path = resolve_project_path("logs/latest_signals.json")
    assert path.name == "latest_signals.json"
    assert "logs" in path.parts


def test_guard_blocks_secret_path() -> None:
    with pytest.raises(McpGuardError):
        resolve_project_path("configs/.env")
    with pytest.raises(McpGuardError):
        resolve_project_path("data/api_key.txt")


def test_guard_blocks_traversal_and_outside() -> None:
    with pytest.raises(McpGuardError):
        resolve_project_path("../etc/passwd")
    with pytest.raises(McpGuardError):
        resolve_project_path("app/scoring/engine.py")


def test_scrub_secrets_redacts_keys() -> None:
    cleaned = scrub_secrets(
        {"api_key": "secret", "symbol": "BTC/USDT", "nested": {"secret": 1}}
    )
    assert cleaned["api_key"] == "[redacted]"
    assert cleaned["symbol"] == "BTC/USDT"
    assert cleaned["nested"]["secret"] == "[redacted]"


def test_tools_degrade_when_artifacts_missing() -> None:
    status = ops_tools.get_bot_status()
    assert status["ok"] is True
    assert status["read_only"] is True
    assert "artifacts" in status

    signals = ops_tools.get_latest_signals(limit=5)
    assert signals["ok"] is True
    assert signals["read_only"] is True

    pipeline = ops_tools.get_agent_pipeline()
    assert pipeline["ok"] is True
    assert pipeline["read_only"] is True

    portfolio = ops_tools.get_portfolio()
    assert portfolio["ok"] is True

    positions = ops_tools.get_open_positions()
    assert positions["ok"] is True

    pnl = ops_tools.get_pnl()
    assert pnl["ok"] is True

    journal = ops_tools.get_trade_journal(limit=5)
    assert journal["ok"] is True
    assert "entries" in journal

    obs = ops_tools.get_chart_observations(limit=5)
    assert obs["ok"] is True


def test_latest_signals_reads_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.mcp.guards as guards

    root = tmp_path
    logs = root / "logs"
    logs.mkdir()
    payload = {
        "timestamp": "2026-07-26T00:00:00+00:00",
        "signals": [{"symbol": "BTC/USDT", "action": "BUY", "confidence": 0.8}],
        "short_signals": [],
        "scan_stats": {"mode": "test"},
    }
    (logs / "latest_signals.json").write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(guards, "PROJECT_ROOT", root)

    result = ops_tools.get_latest_signals(limit=10)
    assert result["ok"] is True
    assert result["available"] is True
    assert result["count"] == 1
    assert result["signals"][0]["symbol"] == "BTC/USDT"


def test_open_positions_from_paper_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import app.mcp.guards as guards

    root = tmp_path
    logs = root / "logs"
    logs.mkdir()
    state = {
        "updated_at": "2026-07-26T01:00:00+00:00",
        "open_positions": {
            "ETH/USDT": {"quantity": 1.5, "entry_price": 3000.0},
        },
        "pending_orders": [],
        "balance": 10000,
        "equity": 10050,
    }
    (logs / "paper_state.json").write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setattr(guards, "PROJECT_ROOT", root)

    result = ops_tools.get_open_positions()
    assert result["ok"] is True
    assert result["available"] is True
    assert result["count"] == 1
    assert result["positions"][0]["symbol"] == "ETH/USDT"

    portfolio = ops_tools.get_portfolio()
    assert portfolio["ok"] is True
    assert portfolio["open_positions_count"] == 1


def test_tool_registry_complete() -> None:
    expected = {
        "get_bot_status",
        "get_portfolio",
        "get_pnl",
        "get_open_positions",
        "get_latest_signals",
        "get_agent_pipeline",
        "get_learning_insights",
        "get_trade_journal",
        "get_chart_observations",
        "get_candles",
        "get_ticker",
        "get_data_source",
    }
    assert set(ops_tools.TOOL_FUNCS) == expected


def test_market_tools_validation() -> None:
    from app.mcp.tools_market import get_candles, get_ticker

    bad_tf = get_candles(symbol="BTC/USDT", timeframe="7d")
    assert bad_tf["ok"] is False
    assert "unsupported_timeframe" in str(bad_tf.get("error", ""))

    bad_ex = get_ticker(symbol="BTC/USDT", exchange="kraken")
    assert bad_ex["ok"] is False
    assert "unsupported_exchange" in str(bad_ex.get("error", ""))

    empty = get_candles(symbol="")
    assert empty["ok"] is False


def test_market_tools_with_fake_service(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.models import Candle
    from app.market.data_service import MarketDataResult
    import app.mcp.tools_market as market_tools

    class FakeService:
        def __init__(self, exchange: str = "binance", fallback_to_sample_data: bool = True) -> None:
            self.exchange = exchange

        def fetch_ohlcv(self, symbol, timeframe="1h", limit=100, *, force_refresh=False):
            candles = [
                Candle(symbol, "2026-07-26T00:00:00Z", 1.0, 2.0, 0.5, 1.5, 100.0),
                Candle(symbol, "2026-07-26T01:00:00Z", 1.5, 2.5, 1.0, 2.0, 110.0),
            ]
            return MarketDataResult(
                symbol=symbol,
                timeframe=timeframe,
                candles=candles[:limit],
                source="test_fake",
                warning=None,
            )

        def fetch_ticker(self, symbol):
            return {"symbol": symbol, "last": 2.0, "bid": 1.9, "ask": 2.1, "api_key": "secret"}

    monkeypatch.setattr(market_tools, "MarketDataService", FakeService, raising=False)

    # Patch import target used inside functions
    import app.market.data_service as ds

    monkeypatch.setattr(ds, "MarketDataService", FakeService)

    candles = market_tools.get_candles(symbol="btcusdt", timeframe="1h", limit=2)
    assert candles["ok"] is True
    assert candles["symbol"] == "BTC/USDT"
    assert candles["count"] == 2
    assert candles["source"] == "test_fake"
    assert candles["candles"][0]["close"] == 1.5

    ticker = market_tools.get_ticker(symbol="ETH/USDT")
    assert ticker["ok"] is True
    assert ticker["ticker"]["last"] == 2.0
    assert ticker["ticker"]["api_key"] == "[redacted]"

    meta = market_tools.get_data_source(symbol="ETH/USDT", limit=2)
    assert meta["ok"] is True
    assert meta["source"] == "test_fake"
    assert "candles" not in meta


def test_tool_registry_includes_market() -> None:
    for name in ("get_candles", "get_ticker", "get_data_source"):
        assert name in ops_tools.TOOL_FUNCS
