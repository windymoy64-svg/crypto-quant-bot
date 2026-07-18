"""Tests for the multi-agent dashboard routes."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.dashboard.routes.agent import (
    learning_insight,
    pipeline_snapshot,
    recent_observations,
    router,
)
from app.learning_agent.models import ChartObservation


@pytest.fixture(autouse=True)
def _redirect_paths(tmp_path, monkeypatch):
    """Redirect all default paths so tests never touch real project files."""
    pipeline_path = tmp_path / "agent_pipeline.json"
    trades_path = tmp_path / "learning_journal.jsonl"
    obs_path = tmp_path / "chart_observations.jsonl"
    monkeypatch.setattr(
        "app.dashboard.routes.agent.DEFAULT_PIPELINE_PATH", str(pipeline_path)
    )
    monkeypatch.setattr(
        "app.dashboard.routes.agent.DEFAULT_TRADE_JOURNAL_PATH", str(trades_path)
    )
    monkeypatch.setattr(
        "app.dashboard.routes.agent.DEFAULT_OBSERVATIONS_PATH", str(obs_path)
    )
    return {
        "pipeline": pipeline_path,
        "trades": trades_path,
        "observations": obs_path,
    }


def test_router_has_expected_routes() -> None:
    paths = [route.path for route in router.routes]
    assert "/api/agent/pipeline" in paths
    assert "/api/agent/learning" in paths
    assert "/api/agent/observations" in paths


def test_pipeline_snapshot_missing_file(_redirect_paths) -> None:
    result = pipeline_snapshot()
    assert result["available"] is False
    assert result["reason"] == "no_pipeline_output_yet"


def test_pipeline_snapshot_returns_payload(_redirect_paths) -> None:
    payload = {"enabled": True, "entries": [], "monitor": []}
    _redirect_paths["pipeline"].write_text(
        json.dumps(payload), encoding="utf-8"
    )
    result = pipeline_snapshot()
    assert result["available"] is True
    assert result["enabled"] is True


def test_pipeline_snapshot_handles_invalid_json(_redirect_paths) -> None:
    _redirect_paths["pipeline"].write_text("not json", encoding="utf-8")
    result = pipeline_snapshot()
    assert result["available"] is False
    assert result["reason"].startswith("read_error")


def test_learning_insight_empty_journal(_redirect_paths) -> None:
    result = learning_insight()
    assert result["available"] is True
    assert result["total_trades"] == 0


def test_observations_empty(_redirect_paths) -> None:
    result = recent_observations(limit=10)
    assert result["available"] is True
    assert result["count"] == 0
    assert result["total_stored"] == 0
    assert result["observations"] == []


def test_observations_returns_recent(_redirect_paths) -> None:
    from app.learning_agent.store import ChartObservationStore

    store = ChartObservationStore(str(_redirect_paths["observations"]))
    for i in range(5):
        store.save(ChartObservation(
            observation_id=f"BTC/USDT:{i}",
            symbol="BTC/USDT",
            timestamp=f"2024-01-0{i+1}T10:00:00Z",
            stage="ENTRY_CANDIDATE",
            scanner_confidence=95.0,
            scanner_gates_passed=True,
            chart_reading={"bias": "BULLISH"},
        ))

    result = recent_observations(limit=3)
    assert result["count"] == 3
    assert result["total_stored"] == 5
    # Most recent last
    assert result["observations"][-1]["observation_id"] == "BTC/USDT:4"


def test_observations_filter_by_stage(_redirect_paths) -> None:
    from app.learning_agent.store import ChartObservationStore

    store = ChartObservationStore(str(_redirect_paths["observations"]))
    store.save(ChartObservation(
        observation_id="A", symbol="BTC/USDT", timestamp="2024-01-01",
        stage="ENTRY_CANDIDATE", scanner_confidence=95.0,
        scanner_gates_passed=True, chart_reading={},
    ))
    store.save(ChartObservation(
        observation_id="B", symbol="BTC/USDT", timestamp="2024-01-02",
        stage="POSITION_MONITOR", scanner_confidence=0.0,
        scanner_gates_passed=False, chart_reading={},
    ))

    entry_only = recent_observations(limit=10, stage="ENTRY_CANDIDATE")
    assert entry_only["count"] == 1
    assert entry_only["observations"][0]["observation_id"] == "A"

    monitor_only = recent_observations(limit=10, stage="POSITION_MONITOR")
    assert monitor_only["count"] == 1


def test_observations_filter_by_symbol(_redirect_paths) -> None:
    from app.learning_agent.store import ChartObservationStore

    store = ChartObservationStore(str(_redirect_paths["observations"]))
    store.save(ChartObservation(
        observation_id="BTC-1", symbol="BTC/USDT", timestamp="2024-01-01",
        stage="ENTRY_CANDIDATE", scanner_confidence=90.0,
        scanner_gates_passed=True, chart_reading={},
    ))
    store.save(ChartObservation(
        observation_id="ETH-1", symbol="ETH/USDT", timestamp="2024-01-02",
        stage="ENTRY_CANDIDATE", scanner_confidence=90.0,
        scanner_gates_passed=True, chart_reading={},
    ))

    result = recent_observations(limit=10, symbol="eth/usdt")
    assert result["count"] == 1
    assert result["observations"][0]["symbol"] == "ETH/USDT"
