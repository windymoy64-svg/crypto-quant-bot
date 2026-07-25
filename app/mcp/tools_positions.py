"""PnL and open positions tools."""

from __future__ import annotations

from typing import Any

from app.mcp.guards import err_payload, ok_payload
from app.mcp.io_utils import read_json
from app.mcp.paths import DEFAULT_ANALYTICS_PATH, DEFAULT_PAPER_STATE_PATH
from app.mcp.tools_status import _normalize_positions


def get_pnl() -> dict[str, Any]:
    """Analytics / performance summary if present."""
    try:
        report = read_json(DEFAULT_ANALYTICS_PATH, None)
        if not isinstance(report, dict) or not report:
            paper = read_json(DEFAULT_PAPER_STATE_PATH, {})
            account = paper.get("account", {}) if isinstance(paper, dict) else {}
            if not isinstance(account, dict):
                account = {}
            return ok_payload(
                {
                    "available": bool(paper),
                    "source": "paper_state_fallback" if paper else "missing",
                    "reason": "analytics_report_missing",
                    "equity": (
                        paper.get("equity", account.get("cash"))
                        if isinstance(paper, dict)
                        else None
                    ),
                    "balance": (
                        paper.get("balance", account.get("cash"))
                        if isinstance(paper, dict)
                        else None
                    ),
                    "realized_pnl": paper.get("realized_pnl") if isinstance(paper, dict) else None,
                    "unrealized_pnl": (
                        paper.get("unrealized_pnl") if isinstance(paper, dict) else None
                    ),
                }
            )
        performance = (
            report.get("performance") if isinstance(report.get("performance"), dict) else {}
        )
        return ok_payload(
            {
                "available": True,
                "source": "analytics_report",
                "path": DEFAULT_ANALYTICS_PATH,
                "performance": performance,
                "summary": report.get("summary"),
                "generated_at": report.get("generated_at"),
                "report_keys": sorted(report.keys()),
            }
        )
    except Exception as exc:  # noqa: BLE001
        return err_payload(exc, tool="get_pnl")


def get_open_positions() -> dict[str, Any]:
    """Open positions from paper state."""
    try:
        paper = read_json(DEFAULT_PAPER_STATE_PATH, None)
        if not isinstance(paper, dict):
            return ok_payload(
                {
                    "available": False,
                    "reason": "no_paper_state",
                    "path": DEFAULT_PAPER_STATE_PATH,
                    "positions": [],
                    "count": 0,
                }
            )
        positions = _normalize_positions(paper.get("open_positions", {}))
        pending = paper.get("pending_orders", paper.get("pending", []))
        if not isinstance(pending, list):
            pending = []
        return ok_payload(
            {
                "available": True,
                "path": DEFAULT_PAPER_STATE_PATH,
                "updated_at": paper.get("updated_at"),
                "count": len(positions),
                "positions": positions,
                "pending_orders_count": len(pending),
                "pending_orders": pending[:50],
            }
        )
    except Exception as exc:  # noqa: BLE001
        return err_payload(exc, tool="get_open_positions")
