"""Trade feedback recorder — connects paper/live trade closures to Learning Agent.

Reads recent trade closures from ``logs/paper_trades.jsonl``, matches each
closure with its earliest ENTRY_CANDIDATE observation from
``ChartObservationStore``, and writes a normalized ``TradeRecord`` to the
learning journal.

Idempotent: uses a checkpoint file to avoid re-processing already-recorded
trades.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.learning_agent.agent import LearningAgent
from app.learning_agent.feedback import build_trade_record_from_dicts
from app.learning_agent.models import ChartObservation
from app.learning_agent.store import ChartObservationStore


DEFAULT_CHECKPOINT_PATH = "data/learning_recorder_checkpoint.json"


class TradeFeedbackRecorder:
    """Reads trade closures and records them to Learning Agent."""

    def __init__(
        self,
        *,
        trades_path: str,
        learning_agent: LearningAgent | None = None,
        observation_store: ChartObservationStore | None = None,
        checkpoint_path: str = DEFAULT_CHECKPOINT_PATH,
    ) -> None:
        self._trades_path = Path(trades_path)
        self._learning = learning_agent or LearningAgent()
        self._observations = observation_store or ChartObservationStore()
        self._checkpoint_path = Path(checkpoint_path)
        self._checkpoint_path.parent.mkdir(parents=True, exist_ok=True)

    def process_new_closures(self) -> list[str]:
        """Record all new closed events. Returns list of recorded trade IDs."""
        if not self._trades_path.exists():
            return []

        checkpoint = self._load_checkpoint()
        recorded_ids: set[str] = set(checkpoint.get("recorded_trade_ids", []))
        new_recorded: list[str] = []

        observations = self._observations.load_all()
        by_symbol_stage: dict[tuple[str, str], list[ChartObservation]] = {}
        for obs in observations:
            by_symbol_stage.setdefault((obs.symbol, obs.stage), []).append(obs)

        with self._trades_path.open("r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("type") != "closed":
                    continue

                position = event.get("position") or {}
                if not isinstance(position, dict):
                    continue
                symbol = str(event.get("symbol") or position.get("symbol") or "")
                if not symbol:
                    continue

                trade_id = self._build_trade_id(symbol, position, event)
                if trade_id in recorded_ids:
                    continue

                entry_obs = self._find_entry_observation(
                    by_symbol_stage, symbol, position
                )
                exit_obs = self._find_exit_observation(
                    by_symbol_stage, symbol, event
                )

                record = build_trade_record_from_dicts(
                    trade_id=trade_id,
                    position=position,
                    close_event=event,
                    entry_observation=entry_obs.to_dict() if entry_obs else None,
                    exit_observation=exit_obs.to_dict() if exit_obs else None,
                )
                self._learning.record_trade(record)
                recorded_ids.add(trade_id)
                new_recorded.append(trade_id)

        self._save_checkpoint({"recorded_trade_ids": sorted(recorded_ids)})
        return new_recorded

    def _build_trade_id(
        self, symbol: str, position: dict[str, Any], event: dict[str, Any]
    ) -> str:
        opened = str(position.get("opened_at", ""))
        closed = str(event.get("timestamp") or position.get("closed_at", ""))
        return f"{symbol}:{opened}:{closed}"

    def _find_entry_observation(
        self,
        by_stage: dict[tuple[str, str], list[ChartObservation]],
        symbol: str,
        position: dict[str, Any],
    ) -> ChartObservation | None:
        candidates = by_stage.get((symbol, "ENTRY_CANDIDATE"), [])
        if not candidates:
            return None
        opened_at = str(position.get("opened_at", ""))
        if not opened_at:
            return candidates[0]
        # Find latest ENTRY_CANDIDATE at or before position open time.
        eligible = [obs for obs in candidates if obs.timestamp <= opened_at]
        return eligible[-1] if eligible else candidates[0]

    def _find_exit_observation(
        self,
        by_stage: dict[tuple[str, str], list[ChartObservation]],
        symbol: str,
        event: dict[str, Any],
    ) -> ChartObservation | None:
        candidates = by_stage.get((symbol, "POSITION_MONITOR"), [])
        if not candidates:
            return None
        closed_at = str(event.get("timestamp", ""))
        if not closed_at:
            return candidates[-1]
        eligible = [obs for obs in candidates if obs.timestamp <= closed_at]
        return eligible[-1] if eligible else None

    def _load_checkpoint(self) -> dict[str, Any]:
        if not self._checkpoint_path.exists():
            return {}
        try:
            return json.loads(self._checkpoint_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_checkpoint(self, payload: dict[str, Any]) -> None:
        with self._checkpoint_path.open("w", encoding="utf-8") as file:
            json.dump(payload, file, indent=2)
