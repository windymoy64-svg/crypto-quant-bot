"""Persistent storage for optional LLM-generated learning insights."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


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