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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter


router = APIRouter(prefix="/api/agent", tags=["agent_pipeline"])


DEFAULT_PIPELINE_PATH = "logs/agent_pipeline.json"
DEFAULT_TRADE_JOURNAL_PATH = "data/learning_journal.jsonl"
DEFAULT_OBSERVATIONS_PATH = "data/chart_observations.jsonl"
DEFAULT_LLM_INSIGHTS_PATH = "data/llm_learning_insights.jsonl"
MAX_OBSERVATIONS_LIMIT = 200
PIPELINE_FRESH_SECONDS = 300


def _parse_timestamp(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


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


@router.get("/snapshot")
def synchronized_snapshot(limit: int = 20) -> dict[str, Any]:
    """Return one timestamped snapshot for every dashboard agent panel.

    Reading the pipeline, learning journal, and observations inside one request
    prevents independently-polled panels from showing different scan cycles.
    ``sync_status`` describes runtime freshness, not trading execution mode.
    """

    snapshot_at = datetime.now(UTC)
    pipeline = pipeline_snapshot()
    learning = learning_insight()
    observations = recent_observations(limit=limit)
    try:
        from app.settings.llm_preferences import load_llm_preferences

        llm = load_llm_preferences().to_dict()
    except Exception:
        llm = {"available": False}
    llm_insights = recent_llm_insights(limit=5)
    generated_at = _parse_timestamp(pipeline.get("generated_at"))
    age_seconds = (
        max(0.0, (snapshot_at - generated_at).total_seconds())
        if generated_at is not None
        else None
    )
    available = pipeline.get("available") is not False and pipeline.get("enabled") is not False
    if not available:
        sync_status = "offline"
    elif pipeline.get("error"):
        sync_status = "error"
    elif age_seconds is None or age_seconds > PIPELINE_FRESH_SECONDS:
        sync_status = "stale"
    else:
        sync_status = "online"

    return {
        "snapshot_at": snapshot_at.isoformat(),
        "sync_status": sync_status,
        "age_seconds": round(age_seconds, 3) if age_seconds is not None else None,
        "pipeline": pipeline,
        "learning": learning,
        "observations": observations,
        "llm": llm,
        "llm_insights": llm_insights,
    }


@router.get("/learning")
def learning_insight() -> dict[str, Any]:
    """Compute the current LearningInsight from stored trades."""
    from app.learning_agent.agent import LearningAgent
    from app.learning_agent.store import ChartObservationStore, TradeStore
    from app.llm.factory import build_agent_llm

    trade_store = TradeStore(DEFAULT_TRADE_JOURNAL_PATH)
    observation_store = ChartObservationStore(DEFAULT_OBSERVATIONS_PATH)
    llm_client, llm_model, llm_base_url = build_agent_llm("learning")
    agent = LearningAgent(
        store=trade_store,
        observation_store=observation_store,
        llm_client=llm_client,
        llm_model=llm_model,
        llm_base_url=llm_base_url,
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
    tail, total = store.load_latest(
        limit,
        stage=stage if isinstance(stage, str) else None,
        symbol=symbol if isinstance(symbol, str) else None,
    )
    return {
        "available": True,
        "count": len(tail),
        "total_stored": total,
        "observations": [obs.to_dict() for obs in tail],
    }


@router.get("/llm/insights")
def recent_llm_insights(limit: int = 20) -> dict[str, Any]:
    """Return persisted optional LLM insights, newest last."""
    from app.learning_agent.insight_store import LLMInsightStore

    limit = max(1, min(int(limit), 100))
    tail, total = LLMInsightStore(DEFAULT_LLM_INSIGHTS_PATH).load_latest(limit)
    return {
        "available": True,
        "count": len(tail),
        "total_stored": total,
        "insights": tail,
    }
