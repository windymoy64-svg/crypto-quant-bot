"""Signals and agent pipeline tools."""

from __future__ import annotations

from typing import Any

from app.mcp.guards import err_payload, ok_payload, resolve_project_path
from app.mcp.io_utils import read_json
from app.mcp.paths import DEFAULT_PIPELINE_PATH, DEFAULT_SIGNALS_PATH


def get_latest_signals(limit: int = 50) -> dict[str, Any]:
    """Latest scanner signals artifact."""
    try:
        limit = max(1, min(int(limit), 200))
        latest = read_json(DEFAULT_SIGNALS_PATH, None)
        if not isinstance(latest, dict):
            return ok_payload(
                {
                    "available": False,
                    "reason": "no_latest_signals",
                    "path": DEFAULT_SIGNALS_PATH,
                    "signals": [],
                    "count": 0,
                }
            )
        signals = latest.get("signals", [])
        short_signals = latest.get("short_signals", [])
        if not isinstance(signals, list):
            signals = []
        if not isinstance(short_signals, list):
            short_signals = []
        return ok_payload(
            {
                "available": True,
                "path": DEFAULT_SIGNALS_PATH,
                "timestamp": latest.get("timestamp"),
                "signals": signals[:limit],
                "count": len(signals),
                "short_signals": short_signals[:limit],
                "short_count": len(short_signals),
                "scan_stats": latest.get("scan_stats"),
                "market_breadth": latest.get("market_breadth"),
                "move_alerts": latest.get("move_alerts"),
            }
        )
    except Exception as exc:  # noqa: BLE001
        return err_payload(exc, tool="get_latest_signals")


def get_agent_pipeline() -> dict[str, Any]:
    """Latest multi-agent pipeline coordinator output."""
    try:
        path = resolve_project_path(DEFAULT_PIPELINE_PATH)
        if not path.exists():
            return ok_payload(
                {
                    "available": False,
                    "reason": "no_pipeline_output_yet",
                    "path": DEFAULT_PIPELINE_PATH,
                }
            )
        payload = read_json(DEFAULT_PIPELINE_PATH, None)
        if not isinstance(payload, dict):
            return ok_payload(
                {
                    "available": False,
                    "reason": "invalid_payload",
                    "path": DEFAULT_PIPELINE_PATH,
                }
            )
        out = dict(payload)
        out["available"] = True
        out["path"] = DEFAULT_PIPELINE_PATH
        return ok_payload(out)
    except Exception as exc:  # noqa: BLE001
        return err_payload(exc, tool="get_agent_pipeline")
