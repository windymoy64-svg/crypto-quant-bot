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
    """Return persisted optional LLM insights, newest last.

    Rows are slimmed for the dashboard: heavy ``input_summary`` (full journal
    snapshots) is dropped so polling does not bloat browser/server RAM.
    """
    from app.learning_agent.insight_store import LLMInsightStore

    limit = max(1, min(int(limit), 100))
    tail, total = LLMInsightStore(DEFAULT_LLM_INSIGHTS_PATH).load_latest(limit)
    return {
        "available": True,
        "count": len(tail),
        "total_stored": total,
        "insights": [_slim_llm_insight_row(row) for row in tail],
    }


def _slim_llm_insight_row(row: dict[str, Any]) -> dict[str, Any]:
    """Keep only fields needed by the LLM Insight History panel."""
    if not isinstance(row, dict):
        return {}
    raw_output = row.get("output") if isinstance(row.get("output"), dict) else {}
    return {
        "timestamp": row.get("timestamp"),
        "agent": row.get("agent"),
        "model": row.get("model"),
        "provider_base_url": row.get("provider_base_url"),
        "output": _normalize_llm_insight_output(raw_output),
    }


def _normalize_llm_insight_output(output: dict[str, Any]) -> dict[str, Any]:
    """Flatten policy_patch / free-form LLM JSON into UI-friendly keys."""
    patch = (
        output.get("policy_patch")
        if isinstance(output.get("policy_patch"), dict)
        else {}
    )
    source = patch or output

    summary = _first_text(
        output.get("human_summary"),
        output.get("summary"),
        output.get("explanation"),
        output.get("analysis"),
        output.get("reason"),
        patch.get("human_summary"),
        patch.get("summary"),
        source.get("message"),
        source.get("text"),
    )
    reasons = _as_str_list(
        output.get("reasons")
        or patch.get("reasons")
        or output.get("reason_codes")
        or patch.get("reason_codes"),
        limit=5,
    )
    recommendations = _as_str_list(output.get("recommendations"), limit=4)
    if not recommendations and patch:
        prefer = _as_str_list(patch.get("prefer_patterns"), limit=4)
        avoid = _as_str_list(patch.get("avoid_patterns"), limit=4)
        if prefer:
            recommendations.append("prefer: " + ", ".join(prefer))
        if avoid:
            recommendations.append("avoid: " + ", ".join(avoid))
        size_mult = patch.get("size_multiplier")
        if size_mult is not None:
            recommendations.append(f"size_multiplier={size_mult}")
        delta = patch.get("min_confluence_delta")
        if delta is not None:
            recommendations.append(f"min_confluence_delta={delta}")
        max_entries = patch.get("max_entries_per_cycle")
        if max_entries is not None:
            recommendations.append(f"max_entries_per_cycle={max_entries}")

    warnings = _as_str_list(output.get("warnings") or patch.get("warnings"), limit=3)
    if not summary and reasons:
        summary = reasons[0]
    if not summary and recommendations:
        summary = recommendations[0]

    compact: dict[str, Any] = {
        "summary": summary,
        "human_summary": summary,
        "reasons": reasons,
        "recommendations": recommendations[:6],
        "warnings": warnings,
    }
    if patch:
        compact["policy_patch"] = {
            k: patch.get(k)
            for k in (
                "min_confluence_delta",
                "block_regimes",
                "prefer_patterns",
                "avoid_patterns",
                "size_multiplier",
                "max_entries_per_cycle",
                "confidence",
                "requires_min_samples",
                "human_summary",
            )
            if patch.get(k) not in (None, "", [], {})
        }
    return compact


def _first_text(*values: object) -> str:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            text = value.strip()
            if text:
                return text
        elif isinstance(value, (int, float, bool)):
            return str(value)
    return ""


def _as_str_list(value: object, *, limit: int = 5) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str):
            text = item.strip()
        elif isinstance(item, dict):
            text = _first_text(
                item.get("text"),
                item.get("message"),
                item.get("summary"),
                item.get("reason"),
                item.get("human_summary"),
            )
        elif item is None:
            continue
        else:
            text = str(item).strip()
        if text:
            out.append(text)
        if len(out) >= limit:
            break
    return out
