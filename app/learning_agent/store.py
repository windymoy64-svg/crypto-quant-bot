"""Learning Agent — memory and knowledge store.

Handles persistence of TradeRecords to JSONL and loading them back.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.learning_agent.models import ChartObservation, TradeRecord


DEFAULT_STORE_PATH = "data/learning_journal.jsonl"
DEFAULT_OBSERVATIONS_PATH = "data/chart_observations.jsonl"


class TradeStore:
    """Append-only JSONL store for trade records."""

    def __init__(self, path: str = DEFAULT_STORE_PATH) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._path

    def save(self, record: TradeRecord) -> None:
        """Append a single trade record to the store."""
        with self._path.open("a", encoding="utf-8") as f:
            json.dump(record.to_dict(), f, separators=(",", ":"))
            f.write("\n")

    def save_many(self, records: list[TradeRecord]) -> None:
        """Append multiple records."""
        if not records:
            return
        with self._path.open("a", encoding="utf-8") as f:
            for record in records:
                json.dump(record.to_dict(), f, separators=(",", ":"))
                f.write("\n")

    def load_all(self) -> list[TradeRecord]:
        """Load all records from the store."""
        if not self._path.exists():
            return []
        records: list[TradeRecord] = []
        with self._path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    records.append(_dict_to_record(data))
                except (json.JSONDecodeError, KeyError, TypeError):
                    continue
        return records

    def count(self) -> int:
        """Count records without loading all into memory."""
        if not self._path.exists():
            return 0
        count = 0
        with self._path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    count += 1
        return count


class ChartObservationStore:
    """Append-only raw Chart Agent observation store."""

    def __init__(self, path: str = DEFAULT_OBSERVATIONS_PATH) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._path

    def save(self, observation: ChartObservation) -> None:
        with self._path.open("a", encoding="utf-8") as f:
            json.dump(observation.to_dict(), f, separators=(",", ":"))
            f.write("\n")

    def load_all(self) -> list[ChartObservation]:
        if not self._path.exists():
            return []
        observations: list[ChartObservation] = []
        with self._path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    data = json.loads(line)
                    observations.append(ChartObservation(
                        observation_id=str(data.get("observation_id", "")),
                        symbol=str(data.get("symbol", "")),
                        timestamp=str(data.get("timestamp", "")),
                        stage=data.get("stage", "ENTRY_CANDIDATE"),
                        scanner_confidence=float(data.get("scanner_confidence", 0.0)),
                        scanner_gates_passed=bool(data.get("scanner_gates_passed", False)),
                        chart_reading=data.get("chart_reading") or {},
                        decision=data.get("decision") or {},
                        meta=data.get("meta") or {},
                    ))
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue
        return observations


def _dict_to_record(data: dict[str, Any]) -> TradeRecord:
    """Convert a dict (from JSON) back to a TradeRecord."""
    return TradeRecord(
        trade_id=str(data.get("trade_id", "")),
        symbol=str(data.get("symbol", "")),
        side=data.get("side", "BUY"),
        timestamp_entry=str(data.get("timestamp_entry", "")),
        timestamp_exit=str(data.get("timestamp_exit", "")),
        entry_price=float(data.get("entry_price", 0)),
        exit_price=float(data.get("exit_price", 0)),
        stop_loss=float(data.get("stop_loss", 0)),
        take_profit_1=float(data.get("take_profit_1", 0)),
        take_profit_2=data.get("take_profit_2"),
        take_profit_3=data.get("take_profit_3"),
        outcome=data.get("outcome", "MANUAL"),
        pnl_percent=float(data.get("pnl_percent", 0)),
        pnl_absolute=float(data.get("pnl_absolute", 0)),
        hold_duration_minutes=float(data.get("hold_duration_minutes", 0)),
        max_favorable_excursion=float(data.get("max_favorable_excursion", 0)),
        max_adverse_excursion=float(data.get("max_adverse_excursion", 0)),
        regime_at_entry=str(data.get("regime_at_entry", "MIXED")),
        bias_at_entry=str(data.get("bias_at_entry", "NEUTRAL")),
        confluence_at_entry=float(data.get("confluence_at_entry", 0)),
        htf_trend_at_entry=str(data.get("htf_trend_at_entry", "SIDE")),
        patterns_at_entry=data.get("patterns_at_entry") or [],
        techniques_at_entry=data.get("techniques_at_entry") or [],
        key_levels_at_entry=data.get("key_levels_at_entry") or [],
        regime_at_exit=str(data.get("regime_at_exit", "MIXED")),
        bias_at_exit=str(data.get("bias_at_exit", "NEUTRAL")),
        exit_reason_detail=str(data.get("exit_reason_detail", "")),
        entry_strategy=str(data.get("entry_strategy", "")),
        entry_confidence=float(data.get("entry_confidence", 0)),
        meta=data.get("meta") or {},
    )
