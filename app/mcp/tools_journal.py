"""Learning journal and chart observation tools."""

from __future__ import annotations

from typing import Any

from app.mcp.guards import err_payload, ok_payload, resolve_project_path, scrub_secrets
from app.mcp.io_utils import read_jsonl_tail
from app.mcp.paths import (
    DEFAULT_OBSERVATIONS_PATH,
    DEFAULT_TRADE_JOURNAL_PATH,
    MAX_JOURNAL_LIMIT,
    MAX_OBSERVATIONS_LIMIT,
)


def get_learning_insights() -> dict[str, Any]:
    """Learning insight from trade journal (reuses LearningAgent when possible)."""
    try:
        from app.learning_agent.agent import LearningAgent
        from app.learning_agent.store import ChartObservationStore, TradeStore

        trade_store = TradeStore(str(resolve_project_path(DEFAULT_TRADE_JOURNAL_PATH)))
        observation_store = ChartObservationStore(
            str(resolve_project_path(DEFAULT_OBSERVATIONS_PATH))
        )
        agent = LearningAgent(store=trade_store, observation_store=observation_store)
        insight = agent.learn()
        payload = insight.to_dict() if hasattr(insight, "to_dict") else dict(insight)
        payload = scrub_secrets(payload)
        if not isinstance(payload, dict):
            payload = {"raw": payload}
        payload["available"] = True
        payload["trade_journal_path"] = DEFAULT_TRADE_JOURNAL_PATH
        payload["observation_store_path"] = DEFAULT_OBSERVATIONS_PATH
        return ok_payload(payload)
    except FileNotFoundError:
        return ok_payload(
            {
                "available": False,
                "reason": "journal_missing",
                "trade_journal_path": DEFAULT_TRADE_JOURNAL_PATH,
            }
        )
    except Exception as exc:  # noqa: BLE001
        rows, total = read_jsonl_tail(DEFAULT_TRADE_JOURNAL_PATH, limit=20)
        return ok_payload(
            {
                "available": False,
                "reason": f"learning_agent_error: {exc}",
                "trade_journal_path": DEFAULT_TRADE_JOURNAL_PATH,
                "recent_trades": rows,
                "total_stored": total,
            }
        )


def get_trade_journal(limit: int = 20, symbol: str | None = None) -> dict[str, Any]:
    """Tail of learning / trade journal JSONL."""
    try:
        limit = max(1, min(int(limit), MAX_JOURNAL_LIMIT))
        rows, total = read_jsonl_tail(DEFAULT_TRADE_JOURNAL_PATH, limit=limit * 3)
        if symbol:
            symbol_u = symbol.upper().replace("-", "/")
            filtered = [
                row
                for row in rows
                if str(row.get("symbol", "")).upper().replace("-", "/") == symbol_u
                or symbol_u in str(row.get("symbol", "")).upper()
            ]
            rows = filtered[-limit:]
        else:
            rows = rows[-limit:]
        path = resolve_project_path(DEFAULT_TRADE_JOURNAL_PATH)
        return ok_payload(
            {
                "available": path.exists(),
                "path": DEFAULT_TRADE_JOURNAL_PATH,
                "count": len(rows),
                "total_stored": total,
                "symbol_filter": symbol,
                "entries": rows,
            }
        )
    except Exception as exc:  # noqa: BLE001
        return err_payload(exc, tool="get_trade_journal")


def get_chart_observations(
    limit: int = 20,
    symbol: str | None = None,
    stage: str | None = None,
) -> dict[str, Any]:
    """Recent chart agent observations."""
    try:
        limit = max(1, min(int(limit), MAX_OBSERVATIONS_LIMIT))
        try:
            from app.learning_agent.store import ChartObservationStore

            store = ChartObservationStore(
                str(resolve_project_path(DEFAULT_OBSERVATIONS_PATH))
            )
            tail, total = store.load_latest(
                limit,
                stage=stage if isinstance(stage, str) else None,
                symbol=symbol if isinstance(symbol, str) else None,
            )
            observations = [
                obs.to_dict() if hasattr(obs, "to_dict") else dict(obs) for obs in tail
            ]
            observations = scrub_secrets(observations)  # type: ignore[assignment]
            return ok_payload(
                {
                    "available": True,
                    "path": DEFAULT_OBSERVATIONS_PATH,
                    "count": len(observations),
                    "total_stored": total,
                    "observations": observations,
                }
            )
        except Exception:
            rows, total = read_jsonl_tail(DEFAULT_OBSERVATIONS_PATH, limit=limit)
            if symbol:
                symbol_u = symbol.upper()
                rows = [r for r in rows if symbol_u in str(r.get("symbol", "")).upper()]
            if stage:
                rows = [r for r in rows if str(r.get("stage", "")) == stage]
            return ok_payload(
                {
                    "available": resolve_project_path(DEFAULT_OBSERVATIONS_PATH).exists(),
                    "path": DEFAULT_OBSERVATIONS_PATH,
                    "count": len(rows),
                    "total_stored": total,
                    "observations": rows[-limit:],
                    "source": "jsonl_tail_fallback",
                }
            )
    except Exception as exc:  # noqa: BLE001
        return err_payload(exc, tool="get_chart_observations")
