"""Learning Agent — memory and knowledge store.

Handles persistence of TradeRecords to JSONL and loading them back.
"""

from __future__ import annotations

import json
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
import threading
from typing import Any

from app.learning_agent.models import ChartObservation, TradeRecord


DEFAULT_STORE_PATH = "data/learning_journal.jsonl"
DEFAULT_OBSERVATIONS_PATH = "data/chart_observations.jsonl"

# Dashboard meminta tail yang sama setiap 5 detik, sedangkan file hanya berubah
# ketika scanner menulis observasi baru. Cache berdasarkan metadata file menjaga
# respons realtime (langsung invalid saat file berubah) tanpa parse puluhan MB
# berulang kali.
_latest_observation_cache: dict[
    tuple[str, int, str | None, str | None],
    tuple[int, int, list[ChartObservation], int],
] = {}
_latest_observation_cache_lock = threading.RLock()


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
                    observations.append(_dict_to_observation(data))
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue
        return observations

    def load_latest(
        self,
        limit: int,
        *,
        stage: str | None = None,
        symbol: str | None = None,
    ) -> tuple[list[ChartObservation], int]:
        # Single-flight: saat startup hanya satu snapshot yang boleh bootstrap
        # tail file besar. Pemanggil paralel menunggu lalu memakai cache.
        with _latest_observation_cache_lock:
            return self._load_latest_locked(
                limit,
                stage=stage,
                symbol=symbol,
            )

    def _load_latest_locked(
        self,
        limit: int,
        *,
        stage: str | None = None,
        symbol: str | None = None,
    ) -> tuple[list[ChartObservation], int]:
        """Read only the latest matching observations with bounded memory.

        The JSONL file is append-only and can grow indefinitely.  Dashboard
        requests only need a small tail, so do not materialize the complete
        history on every realtime snapshot.
        """
        if limit <= 0 or not self._path.exists():
            return [], 0

        target_stage = stage.upper() if stage else None
        target_symbol = symbol.upper() if symbol else None
        try:
            stat = self._path.stat()
        except OSError:
            return [], 0
        cache_key = (str(self._path.resolve()), limit, target_stage, target_symbol)
        signature = (stat.st_mtime_ns, stat.st_size)
        with _latest_observation_cache_lock:
            cached = _latest_observation_cache.get(cache_key)
            if cached and cached[:2] == signature:
                return list(cached[2]), cached[3]

        # Append-only fast path: lanjut dari byte terakhir yang sudah diproses.
        # Rotasi/truncate terdeteksi ketika ukuran mengecil dan otomatis kembali
        # ke full scan satu kali.
        append_offset = 0
        if cached and stat.st_size > cached[1]:
            append_offset = cached[1]
            latest: deque[ChartObservation] = deque(cached[2], maxlen=limit)
            total = cached[3]
        else:
            latest = deque(maxlen=limit)
            total = 0
        try:
            with self._path.open("r", encoding="utf-8") as file:
                if append_offset:
                    file.seek(append_offset)
                for line in file:
                    try:
                        data = json.loads(line)
                        if not isinstance(data, dict):
                            continue
                        observation = _dict_to_observation(data)
                    except (json.JSONDecodeError, TypeError, ValueError):
                        continue
                    if target_stage and str(observation.stage).upper() != target_stage:
                        continue
                    if target_symbol and observation.symbol.upper() != target_symbol:
                        continue
                    total += 1
                    latest.append(observation)
        except OSError:
            return [], 0
        result = list(latest)
        with _latest_observation_cache_lock:
            _latest_observation_cache[cache_key] = (*signature, result, total)
            # Query dashboard terbatas, tetapi cegah kombinasi filter arbitrer
            # membuat cache tumbuh tanpa batas.
            if len(_latest_observation_cache) > 64:
                oldest = next(iter(_latest_observation_cache))
                _latest_observation_cache.pop(oldest, None)
        return list(result), total


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


def _dict_to_observation(data: dict[str, Any]) -> ChartObservation:
    return ChartObservation(
        observation_id=str(data.get("observation_id", "")),
        symbol=str(data.get("symbol", "")),
        timestamp=str(data.get("timestamp", "")),
        stage=data.get("stage", "ENTRY_CANDIDATE"),
        scanner_confidence=float(data.get("scanner_confidence", 0.0)),
        scanner_gates_passed=bool(data.get("scanner_gates_passed", False)),
        chart_reading=data.get("chart_reading") or {},
        decision=data.get("decision") or {},
        meta=data.get("meta") or {},
    )
