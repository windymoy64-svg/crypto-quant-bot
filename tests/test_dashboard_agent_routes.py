"""Tests for the multi-agent dashboard routes."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.dashboard.routes.agent import (
    learning_insight,
    pipeline_snapshot,
    recent_llm_insights,
    recent_observations,
    router,
    synchronized_snapshot,
)
from app.learning_agent.models import ChartObservation


@pytest.fixture(autouse=True)
def _redirect_paths(tmp_path, monkeypatch):
    """Redirect all default paths so tests never touch real project files."""
    pipeline_path = tmp_path / "agent_pipeline.json"
    trades_path = tmp_path / "learning_journal.jsonl"
    obs_path = tmp_path / "chart_observations.jsonl"
    llm_insights_path = tmp_path / "llm_learning_insights.jsonl"
    monkeypatch.setattr(
        "app.dashboard.routes.agent.DEFAULT_PIPELINE_PATH", str(pipeline_path)
    )
    monkeypatch.setattr(
        "app.dashboard.routes.agent.DEFAULT_TRADE_JOURNAL_PATH", str(trades_path)
    )
    monkeypatch.setattr(
        "app.dashboard.routes.agent.DEFAULT_OBSERVATIONS_PATH", str(obs_path)
    )
    monkeypatch.setattr(
        "app.dashboard.routes.agent.DEFAULT_LLM_INSIGHTS_PATH", str(llm_insights_path)
    )
    return {
        "pipeline": pipeline_path,
        "trades": trades_path,
        "observations": obs_path,
        "llm_insights": llm_insights_path,
    }


def test_router_has_expected_routes() -> None:
    paths = [route.path for route in router.routes]
    assert "/api/agent/pipeline" in paths
    assert "/api/agent/learning" in paths
    assert "/api/agent/observations" in paths
    assert "/api/agent/snapshot" in paths
    assert "/api/agent/llm/insights" in paths


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


def test_synchronized_snapshot_marks_fresh_pipeline_online(_redirect_paths) -> None:
    from datetime import UTC, datetime

    _redirect_paths["pipeline"].write_text(
        json.dumps({
            "enabled": True,
            "generated_at": datetime.now(UTC).isoformat(),
            "entries": [],
            "monitor": [],
        }),
        encoding="utf-8",
    )

    result = synchronized_snapshot(limit=10)

    assert result["sync_status"] == "online"
    assert result["age_seconds"] is not None
    assert result["pipeline"]["available"] is True
    assert result["learning"]["available"] is True
    assert result["observations"]["available"] is True


def test_synchronized_snapshot_marks_missing_pipeline_offline(_redirect_paths) -> None:
    result = synchronized_snapshot(limit=10)

    assert result["sync_status"] == "offline"
    assert result["age_seconds"] is None


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


def test_llm_insights_returns_recent_rows(_redirect_paths) -> None:
    _redirect_paths["llm_insights"].write_text(
        "\n".join([
            json.dumps({
                "timestamp": "2024-01-01T00:00:00Z",
                "agent": "learning",
                "provider_base_url": "https://api.example.com/v1",
                "model": "gpt-4.1",
                "input_summary": {"record_count": 1, "recent_trades": [{"trade_id": "x"}]},
                "output": {"summary": "old"},
            }),
            json.dumps({
                "timestamp": "2024-01-02T00:00:00Z",
                "agent": "learning",
                "provider_base_url": "https://api.example.com/v1",
                "model": "gpt-4.1",
                "input_summary": {
                    "record_count": 99,
                    "deterministic_insight": {"total_trades": 99},
                    "recent_trades": [{"trade_id": "huge-payload"}],
                },
                "output": {
                    "policy_patch": {
                        "human_summary": "What worked: high vol. What failed: marubozu churn.",
                        "reasons": ["positive expectancy", "avoid marubozu"],
                        "prefer_patterns": ["dark_cloud_cover"],
                        "avoid_patterns": ["marubozu"],
                        "size_multiplier": 0.75,
                        "min_confluence_delta": 3,
                        "max_entries_per_cycle": 1,
                        "confidence": 0.8,
                    }
                },
            }),
        ]),
        encoding="utf-8",
    )

    result = recent_llm_insights(limit=5)

    assert result["available"] is True
    assert result["count"] == 2
    assert result["total_stored"] == 2
    latest = result["insights"][-1]
    assert latest["output"]["summary"].startswith("What worked")
    assert "prefer: dark_cloud_cover" in latest["output"]["recommendations"]
    # Heavy journal snapshot must not be shipped to the browser.
    assert "input_summary" not in latest
    assert result["insights"][0]["output"]["summary"] == "old"


def test_llm_insights_flattens_policy_patch_for_ui(_redirect_paths) -> None:
    from app.dashboard.routes.agent import _normalize_llm_insight_output

    out = _normalize_llm_insight_output(
        {
            "policy_patch": {
                "human_summary": "Keep trading but cut size.",
                "reasons": ["low winrate", "positive expectancy"],
                "prefer_patterns": ["dark_cloud_cover"],
                "avoid_patterns": ["marubozu", "evening_star"],
                "size_multiplier": 0.75,
            }
        }
    )
    assert out["summary"] == "Keep trading but cut size."
    assert out["reasons"][0] == "low winrate"
    assert any(r.startswith("prefer:") for r in out["recommendations"])
