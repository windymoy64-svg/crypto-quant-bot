"""Dashboard routes for the multi-agent pipeline and Learning Agent insights.

Read-only advisory endpoints:

- ``GET /api/agent/pipeline`` — latest coordinator output from
  ``logs/agent_pipeline.json``.
- ``GET /api/agent/learning`` — computed ``LearningInsight`` from the trade
  journal (hot/cold patterns, best regime, confluence calibration).
- ``GET /api/agent/observations`` — most recent Chart Agent observations
  (bounded to avoid loading the whole file).

All endpoints degrade gracefully to an empty payload when files are missing so
the dashboard never breaks just because the pipeline hasn't run yet.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter


router = APIRouter(prefix="/api/agent", tags=["agent_pipeline"])


DEFAULT_PIPELINE_PATH = "logs/agent_pipeline.json"
DEFAULT_TRADE_JOURNAL_PATH = "data/learning_journal.jsonl"
DEFAULT_OBSERVATIONS_PATH = "data/chart_observations.jsonl"
MAX_OBSERVATIONS_LIMIT = 200


@router.get("/pipeline")
def pipeline_snapshot() -> dict[str, Any]:
    """Return the latest agent pipeline coordinator output."""
    path = Path(DEFAULT_PIPELINE_PATH)
    if not path.exists():
        return {
            "available": False,
            "reason": "no_pipeline_output_yet",
            "path": str(path),
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return {"available": False, "reason": "invalid_payload"}
        payload["available"] = True
        return payload
    except (OSError, json.JSONDecodeError) as exc:
        return {"available": False, "reason": f"read_error: {exc}"}


@router.get("/learning")
def learning_insight() -> dict[str, Any]:
    """Compute the current LearningInsight from stored trades."""
    from app.learning_agent.agent import LearningAgent
    from app.learning_agent.store import ChartObservationStore, TradeStore

    trade_store = TradeStore(DEFAULT_TRADE_JOURNAL_PATH)
    observation_store = ChartObservationStore(DEFAULT_OBSERVATIONS_PATH)
    agent = LearningAgent(
        store=trade_store, observation_store=observation_store
    )

    insight = agent.learn()
    payload = insight.to_dict()
    payload["available"] = True
    payload["trade_journal_path"] = DEFAULT_TRADE_JOURNAL_PATH
    payload["observation_store_path"] = DEFAULT_OBSERVATIONS_PATH
    return payload


@router.get("/observations")
def recent_observations(
    limit: int = 20,
    stage: str | None = None,
    symbol: str | None = None,
) -> dict[str, Any]:
    """Return the most recent Chart Agent observations."""
    from app.learning_agent.store import ChartObservationStore

    limit = max(1, min(int(limit), MAX_OBSERVATIONS_LIMIT))

    store = ChartObservationStore(DEFAULT_OBSERVATIONS_PATH)
    observations = store.load_all()
    if stage and isinstance(stage, str):
        target_stage = stage.upper()
        observations = [o for o in observations if o.stage == target_stage]
    if symbol and isinstance(symbol, str):
        target_symbol = symbol.upper()
        observations = [
            o for o in observations if o.symbol.upper() == target_symbol
        ]

    # Return the most recent ``limit`` in chronological order.
    tail = observations[-limit:]
    return {
        "available": True,
        "count": len(tail),
        "total_stored": len(observations),
        "observations": [obs.to_dict() for obs in tail],
    }
