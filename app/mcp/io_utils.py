"""Shared JSON/JSONL helpers for Ops MCP tools."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from app.mcp.guards import resolve_project_path, scrub_secrets


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def read_json(relative_path: str, default: Any = None) -> Any:
    path = resolve_project_path(relative_path)
    if not path.exists():
        return default
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default
    return scrub_secrets(payload)


def read_jsonl_tail(
    relative_path: str, limit: int
) -> tuple[list[dict[str, Any]], int | None]:
    """Return last ``limit`` JSON objects and total non-empty line count."""
    path = resolve_project_path(relative_path)
    if not path.exists():
        return [], 0
    try:
        tail: list[str] = []
        total = 0
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                total += 1
                tail.append(stripped)
                if len(tail) > limit:
                    tail.pop(0)
        rows: list[dict[str, Any]] = []
        for raw in tail:
            try:
                item = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                rows.append(scrub_secrets(item))  # type: ignore[arg-type]
        return rows, total
    except OSError:
        return [], None


def artifact_exists(relative_path: str) -> bool:
    try:
        return resolve_project_path(relative_path).exists()
    except Exception:
        return False
