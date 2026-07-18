"""Tests for the agent pipeline bridge to run_realtime.py."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from app.agent_pipeline.bridge import (
    AgentPipelineRuntimeConfig,
    run_pipeline_bridge,
)
from app.core.models import Candle
from app.market.data_service import MarketDataResult


def _candle(i: int, base: float = 100.0) -> Candle:
    trend = i * 0.5
    open_price = base + trend
    close = open_price + 0.35
    return Candle(
        symbol="BTC/USDT", timestamp=f"2024-01-01T{i:02d}:00:00Z",
        open=open_price, high=close + 0.2, low=open_price - 0.3,
        close=close, volume=1000.0,
    )


def _market_data_stub() -> MagicMock:
    """Stub MarketDataService returning uptrend candles for any request."""
    service = MagicMock()

    def fetch_ohlcv(symbol: str, timeframe: str = "1h", limit: int = 100, **kwargs):
        return MarketDataResult(
            symbol=symbol, timeframe=timeframe,
            candles=[_candle(i) for i in range(min(limit, 30))],
            source="stub",
        )

    service.fetch_ohlcv = fetch_ohlcv
    return service


def test_bridge_returns_disabled_when_config_disabled(tmp_path: Path) -> None:
    config = AgentPipelineRuntimeConfig.from_dict(
        {"enabled": False, "output_path": str(tmp_path / "out.json")}
    )
    result = run_pipeline_bridge(
        config=config,
        scanner_results=[],
        open_positions={},
        market_data=_market_data_stub(),
    )
    assert result["enabled"] is False
    assert result["reason"] == "pipeline_disabled_by_config"


def test_bridge_skips_low_confidence_candidates(tmp_path: Path) -> None:
    config = AgentPipelineRuntimeConfig.from_dict({
        "enabled": True,
        "min_scanner_confidence": 90.0,
        "output_path": str(tmp_path / "pipeline.json"),
        "monitor_positions": False,
    })
    result = run_pipeline_bridge(
        config=config,
        scanner_results=[
            {"symbol": "BTC/USDT", "action": "BUY", "confidence": 85.0, "failed_gates": []},
            {"symbol": "ETH/USDT", "action": "BUY", "confidence": 95.0, "failed_gates": ["volume"]},
        ],
        open_positions={},
        market_data=_market_data_stub(),
    )
    assert result["enabled"] is True
    # Both candidates filtered before Chart Agent is called
    assert result["entries"] == []


def test_bridge_processes_qualified_candidate(tmp_path: Path) -> None:
    config = AgentPipelineRuntimeConfig.from_dict({
        "enabled": True,
        "min_scanner_confidence": 90.0,
        "output_path": str(tmp_path / "pipeline.json"),
        "monitor_positions": False,
    })
    result = run_pipeline_bridge(
        config=config,
        scanner_results=[
            {"symbol": "BTC/USDT", "action": "BUY", "confidence": 95.0, "failed_gates": []},
        ],
        open_positions={},
        market_data=_market_data_stub(),
    )
    assert len(result["entries"]) == 1
    entry = result["entries"][0]
    assert entry["symbol"] == "BTC/USDT"
    assert entry["scanner_confidence"] == 95.0
    assert entry["result"]["stage"] == "ENTRY"
    assert entry["result"]["chart_reading"] is not None


def test_bridge_monitors_open_positions(tmp_path: Path) -> None:
    config = AgentPipelineRuntimeConfig.from_dict({
        "enabled": True,
        "output_path": str(tmp_path / "pipeline.json"),
    })
    result = run_pipeline_bridge(
        config=config,
        scanner_results=[],
        open_positions={
            "BTC/USDT": {
                "symbol": "BTC/USDT",
                "side": "BUY",
                "remaining_size": 0.5,
                "entry": 100.0,
                "last_price": 105.0,
            },
        },
        market_data=_market_data_stub(),
    )
    assert len(result["monitor"]) == 1
    assert result["monitor"][0]["symbol"] == "BTC/USDT"
    assert result["monitor"][0]["result"]["stage"] == "POSITION_MONITOR"


def test_bridge_writes_output_artifact(tmp_path: Path) -> None:
    output = tmp_path / "pipeline.json"
    config = AgentPipelineRuntimeConfig.from_dict({
        "enabled": True,
        "output_path": str(output),
        "monitor_positions": False,
    })
    run_pipeline_bridge(
        config=config,
        scanner_results=[
            {"symbol": "BTC/USDT", "action": "BUY", "confidence": 95.0, "failed_gates": []},
        ],
        open_positions={},
        market_data=_market_data_stub(),
    )
    assert output.exists()
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["enabled"] is True
    assert payload["execute_decisions"] is False
    assert len(payload["entries"]) == 1


def test_bridge_execution_stays_off_by_default(tmp_path: Path) -> None:
    config = AgentPipelineRuntimeConfig.from_dict({
        "enabled": True,
        "output_path": str(tmp_path / "pipeline.json"),
        "monitor_positions": False,
    })
    result = run_pipeline_bridge(
        config=config,
        scanner_results=[
            {"symbol": "BTC/USDT", "action": "BUY", "confidence": 95.0, "failed_gates": []},
        ],
        open_positions={},
        market_data=_market_data_stub(),
    )
    assert result["execute_decisions"] is False
    assert result["entries"][0]["result"]["execution"] is None


def test_bridge_config_from_dict_defaults() -> None:
    cfg = AgentPipelineRuntimeConfig.from_dict(None)
    assert cfg.enabled is False
    assert cfg.execute_decisions is False
    assert cfg.min_scanner_confidence == 90.0
