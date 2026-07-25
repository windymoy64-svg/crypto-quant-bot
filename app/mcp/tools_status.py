"""Status and portfolio tools."""

from __future__ import annotations

from typing import Any

from app.mcp.guards import PROJECT_ROOT, err_payload, ok_payload, scrub_secrets
from app.mcp.io_utils import artifact_exists, now_iso, read_json
from app.mcp.paths import (
    DEFAULT_ANALYTICS_PATH,
    DEFAULT_OBSERVATIONS_PATH,
    DEFAULT_PAPER_STATE_PATH,
    DEFAULT_PIPELINE_PATH,
    DEFAULT_PORTFOLIO_STATE_PATH,
    DEFAULT_SIGNALS_PATH,
    DEFAULT_TRADE_JOURNAL_PATH,
)


def _artifact_flags() -> dict[str, bool]:
    names = (
        DEFAULT_SIGNALS_PATH,
        DEFAULT_PAPER_STATE_PATH,
        DEFAULT_PIPELINE_PATH,
        DEFAULT_ANALYTICS_PATH,
        DEFAULT_TRADE_JOURNAL_PATH,
        DEFAULT_OBSERVATIONS_PATH,
        DEFAULT_PORTFOLIO_STATE_PATH,
    )
    return {rel: artifact_exists(rel) for rel in names}


def _normalize_positions(raw: object) -> list[dict[str, Any]]:
    positions: list[dict[str, Any]] = []
    if isinstance(raw, dict):
        for symbol, value in raw.items():
            if isinstance(value, dict):
                row = dict(value)
                row.setdefault("symbol", symbol)
                positions.append(row)
            else:
                positions.append({"symbol": symbol, "raw": value})
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                positions.append(item)
    return positions


def get_bot_status() -> dict[str, Any]:
    """Health-style status from artifacts + optional system monitor."""
    try:
        system: dict[str, Any] = {}
        try:
            from app.monitoring import system_health_monitor

            snap = system_health_monitor.snapshot()
            if isinstance(snap, dict):
                system = scrub_secrets(snap)  # type: ignore[assignment]
        except Exception as exc:  # noqa: BLE001
            system = {"available": False, "error": str(exc)}

        paper = read_json(DEFAULT_PAPER_STATE_PATH, {})
        signals = read_json(DEFAULT_SIGNALS_PATH, {})
        pipeline = read_json(DEFAULT_PIPELINE_PATH, {})
        return ok_payload(
            {
                "status": "ok",
                "service": "crypto-quant-bot-ops-mcp",
                "timestamp": now_iso(),
                "project_root": str(PROJECT_ROOT),
                "artifacts": _artifact_flags(),
                "system": system,
                "paper_updated_at": paper.get("updated_at") if isinstance(paper, dict) else None,
                "signals_timestamp": (
                    signals.get("timestamp") if isinstance(signals, dict) else None
                ),
                "pipeline_generated_at": (
                    pipeline.get("generated_at") if isinstance(pipeline, dict) else None
                ),
                "pipeline_enabled": (
                    pipeline.get("enabled") if isinstance(pipeline, dict) else None
                ),
            }
        )
    except Exception as exc:  # noqa: BLE001
        return err_payload(exc, tool="get_bot_status")


def get_portfolio() -> dict[str, Any]:
    """Paper / portfolio snapshot (read-only)."""
    try:
        paper = read_json(DEFAULT_PAPER_STATE_PATH, None)
        portfolio = read_json(DEFAULT_PORTFOLIO_STATE_PATH, None)
        if paper is None and portfolio is None:
            return ok_payload(
                {
                    "available": False,
                    "reason": "no_paper_or_portfolio_state",
                    "paths": {
                        "paper": DEFAULT_PAPER_STATE_PATH,
                        "portfolio": DEFAULT_PORTFOLIO_STATE_PATH,
                    },
                }
            )
        account: dict[str, Any] = {}
        if isinstance(paper, dict) and isinstance(paper.get("account"), dict):
            account = paper["account"]
        open_positions = _normalize_positions(
            paper.get("open_positions", []) if isinstance(paper, dict) else []
        )
        equity = balance = None
        if isinstance(paper, dict):
            equity = paper.get("equity", account.get("equity", account.get("cash")))
            balance = paper.get("balance", account.get("cash", paper.get("available_balance")))
        return ok_payload(
            {
                "available": True,
                "source": "paper_state" if paper is not None else "portfolio_state",
                "timestamp": paper.get("updated_at") if isinstance(paper, dict) else None,
                "equity": equity,
                "balance": balance,
                "available_balance": (
                    paper.get("available_balance") if isinstance(paper, dict) else None
                ),
                "open_positions_count": len(open_positions),
                "open_positions": open_positions,
                "account": account,
                "portfolio_state": portfolio if isinstance(portfolio, dict) else None,
            }
        )
    except Exception as exc:  # noqa: BLE001
        return err_payload(exc, tool="get_portfolio")
