"""Backtest tools for Ops MCP (offline research, guarded)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.mcp.guards import (
    PROJECT_ROOT,
    err_payload,
    ok_payload,
    resolve_project_path,
    scrub_secrets,
)

DEFAULT_BACKTEST_DIR = "logs/backtests"
MAX_BACKTEST_LIMIT = 1000
MIN_BACKTEST_LIMIT = 50
MAX_LIST_ARTIFACTS = 50
ALLOWED_EXCHANGES = frozenset({"binance", "bitunix", "okx"})
ALLOWED_TIMEFRAMES = frozenset(
    {"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"}
)


def _normalize_symbol(symbol: str) -> str:
    raw = str(symbol or "").strip().upper().replace("-", "/")
    if not raw:
        raise ValueError("symbol_required")
    if "/" not in raw and raw.endswith("USDT") and len(raw) > 4:
        raw = f"{raw[:-4]}/{raw[-4:]}"
    return raw


def _normalize_exchange(exchange: str) -> str:
    ex = str(exchange or "binance").strip().lower()
    if ex not in ALLOWED_EXCHANGES:
        raise ValueError(f"unsupported_exchange:{ex}")
    return ex


def _normalize_timeframe(timeframe: str) -> str:
    tf = str(timeframe or "1h").strip().lower()
    if tf not in ALLOWED_TIMEFRAMES:
        raise ValueError(f"unsupported_timeframe:{tf}")
    return tf


def _normalize_limit(limit: int) -> int:
    return max(MIN_BACKTEST_LIMIT, min(int(limit), MAX_BACKTEST_LIMIT))


def _summary_from_artifact(data: dict[str, Any], path: Path) -> dict[str, Any]:
    config = data.get("config") if isinstance(data.get("config"), dict) else {}
    metrics = data.get("metrics") if isinstance(data.get("metrics"), dict) else {}
    try:
        rel = str(path.resolve().relative_to(PROJECT_ROOT.resolve()))
    except ValueError:
        rel = str(path)
    return {
        "path": rel,
        "symbol": config.get("symbol"),
        "exchange": config.get("exchange"),
        "timeframe": config.get("timeframe"),
        "candles": data.get("candles"),
        "data_source": data.get("data_source"),
        "trades": metrics.get("trades"),
        "winrate": metrics.get("winrate"),
        "profit": metrics.get("profit"),
        "max_drawdown": metrics.get("max_drawdown"),
        "sharpe": metrics.get("sharpe"),
        "updated_at": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
    }


def list_backtest_artifacts(limit: int = 20) -> dict[str, Any]:
    """List recent backtest JSON artifacts under logs/backtests/."""
    try:
        limit = max(1, min(int(limit), MAX_LIST_ARTIFACTS))
        directory = resolve_project_path(DEFAULT_BACKTEST_DIR)
        if not directory.exists():
            return ok_payload(
                {
                    "available": False,
                    "reason": "backtests_dir_missing",
                    "path": DEFAULT_BACKTEST_DIR,
                    "results": [],
                    "count": 0,
                }
            )
        files = sorted(
            directory.glob("*_backtest.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:limit]
        if not files:
            files = sorted(
                directory.glob("*.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )[:limit]
        results: list[dict[str, Any]] = []
        for path in files:
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                results.append({"path": str(path.name), "available": False})
                continue
            if isinstance(raw, dict):
                results.append(_summary_from_artifact(scrub_secrets(raw), path))  # type: ignore[arg-type]
        return ok_payload(
            {
                "available": True,
                "path": DEFAULT_BACKTEST_DIR,
                "count": len(results),
                "results": results,
            }
        )
    except Exception as exc:  # noqa: BLE001
        return err_payload(exc, tool="list_backtest_artifacts")
