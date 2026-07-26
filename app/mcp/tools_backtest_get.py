"""get_backtest_artifact tool."""

from __future__ import annotations

import json
from typing import Any

from app.mcp.guards import err_payload, ok_payload, resolve_project_path, scrub_secrets
from app.mcp.tools_backtest import DEFAULT_BACKTEST_DIR, _summary_from_artifact


def get_backtest_artifact(name: str) -> dict[str, Any]:
    """Read one backtest JSON artifact by filename (under logs/backtests only)."""
    try:
        raw_name = str(name or "").strip().replace("\\", "/")
        if not raw_name or "/" in raw_name or ".." in raw_name:
            raise ValueError("invalid_artifact_name")
        if not raw_name.endswith(".json"):
            raw_name = f"{raw_name}.json"
        rel = f"{DEFAULT_BACKTEST_DIR}/{raw_name}"
        path = resolve_project_path(rel)
        if not path.exists():
            return ok_payload({"available": False, "reason": "not_found", "path": rel})
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return ok_payload({"available": False, "reason": "invalid_payload", "path": rel})
        cleaned = scrub_secrets(data)
        assert isinstance(cleaned, dict)
        trades = cleaned.get("trades")
        equity = cleaned.get("equity_curve")
        if isinstance(trades, list) and len(trades) > 100:
            cleaned["trades"] = trades[-100:]
            cleaned["trades_truncated"] = True
        if isinstance(equity, list) and len(equity) > 200:
            cleaned["equity_curve"] = equity[-200:]
            cleaned["equity_truncated"] = True
        return ok_payload(
            {
                "available": True,
                "path": rel,
                "summary": _summary_from_artifact(cleaned, path),  # type: ignore[arg-type]
                "artifact": cleaned,
            }
        )
    except Exception as exc:  # noqa: BLE001
        return err_payload(exc, tool="get_backtest_artifact")
