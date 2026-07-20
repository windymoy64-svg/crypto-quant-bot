"""Persistent storage for optional LLM-generated learning insights."""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from pathlib import Path
import threading
from typing import Any


_latest_insight_cache: dict[
    tuple[str, int], tuple[int, int, list[dict[str, Any]], int]
] = {}
_latest_insight_cache_lock = threading.RLock()


@dataclass(frozen=True)
class LLMInsightRecord:
    timestamp: str
    agent: str
    provider_base_url: str
    model: str
    input_summary: dict[str, Any]
    output: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "agent": self.agent,
            "provider_base_url": self.provider_base_url,
            "model": self.model,
            "input_summary": self.input_summary,
            "output": self.output,
        }


class LLMInsightStore:
    def __init__(self, path: str = "data/llm_learning_insights.jsonl") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def save(self, record: LLMInsightRecord) -> None:
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")

    def load_all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        rows: list[dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(data, dict):
                    rows.append(data)
        return rows

    def load_latest(self, limit: int) -> tuple[list[dict[str, Any]], int]:
        # Hindari beberapa request startup memindai file yang sama bersamaan.
        with _latest_insight_cache_lock:
            return self._load_latest_locked(limit)

    def _load_latest_locked(self, limit: int) -> tuple[list[dict[str, Any]], int]:
        """Return the newest rows and valid row count using bounded memory."""
        if limit <= 0 or not self.path.exists():
            return [], 0
        try:
            stat = self.path.stat()
        except OSError:
            return [], 0
        cache_key = (str(self.path.resolve()), limit)
        signature = (stat.st_mtime_ns, stat.st_size)
        with _latest_insight_cache_lock:
            cached = _latest_insight_cache.get(cache_key)
            if cached and cached[:2] == signature:
                return list(cached[2]), cached[3]

        append_offset = 0
        if cached and stat.st_size > cached[1]:
            append_offset = cached[1]
            rows: deque[dict[str, Any]] = deque(cached[2], maxlen=limit)
            total = cached[3]
        else:
            rows = deque(maxlen=limit)
            total = 0
        try:
            with self.path.open("r", encoding="utf-8") as file:
                if append_offset:
                    file.seek(append_offset)
                for line in file:
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(data, dict):
                        total += 1
                        rows.append(data)
        except OSError:
            return [], 0
        result = list(rows)
        with _latest_insight_cache_lock:
            _latest_insight_cache[cache_key] = (*signature, result, total)
            if len(_latest_insight_cache) > 32:
                oldest = next(iter(_latest_insight_cache))
                _latest_insight_cache.pop(oldest, None)
        return list(result), total

    def latest_input_fingerprint(self) -> tuple[int, str] | None:
        """Fingerprint of the input data used for the most recent LLM insight.

        Returns ``(record_count, latest_trade_id)`` from the last stored
        insight's ``input_summary``, or ``None`` when no insight exists yet.
        Used to skip regenerating an identical insight when the underlying
        trade data has not changed.
        """
        latest = self.latest()
        if latest is None:
            return None
        summary = latest.get("input_summary") or {}
        if not isinstance(summary, dict):
            return None
        try:
            record_count = int(summary.get("record_count") or 0)
        except (TypeError, ValueError):
            record_count = 0
        recent = summary.get("recent_trades")
        latest_trade_id = ""
        if isinstance(recent, list) and recent:
            last = recent[-1]
            if isinstance(last, dict):
                latest_trade_id = str(last.get("trade_id") or "")
        return (record_count, latest_trade_id)

    def latest(self) -> dict[str, Any] | None:
        """Return the most recent insight row without parsing the whole file."""
        if not self.path.exists():
            return None
        last_line = ""
        with self.path.open("r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                if line:
                    last_line = line
        if not last_line:
            return None
        try:
            data = json.loads(last_line)
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None