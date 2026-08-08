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

        # Do not call ChartObservationStore.load_all() here.  The observation
        # JSONL is intentionally append-only and can become hundreds of MB;
        # materializing every nested ChartReading caused RSS spikes near 1 GB.
        # Observations are loaded bounded and only for symbols with a new
        # closure, below in _find_*_observation.
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

                entry_obs = self._find_entry_observation(symbol, position)
                exit_obs = self._find_exit_observation(symbol, event)

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

    def process_bitunix_closed_positions(
        self, closed_positions: list[dict[str, Any]],
    ) -> list[str]:
        """Record authoritative Bitunix full closes into the learning journal.

        Bitunix exposes completed positions through its private position-history
        response rather than the paper JSONL event stream.  Normalize the rows
        to the existing feedback schema and use the same idempotent checkpoint
        contract as paper closures.
        """
        checkpoint = self._load_checkpoint()
        recorded_ids: set[str] = set(checkpoint.get("recorded_trade_ids", []))
        # The dedicated live checkpoint may be introduced after a shared paper
        # checkpoint already recorded a close. Protect the append-only journal
        # itself against duplicates during that one-time migration.
        recorded_ids.update(self._learning.recorded_trade_ids())
        new_recorded: list[str] = []
        for raw in closed_positions:
            if not isinstance(raw, dict):
                continue
            position = self._normalize_bitunix_position(raw)
            symbol = str(position.get("symbol") or "")
            closed_at = str(raw.get("closed_at") or raw.get("update_time") or "")
            if not symbol or not closed_at:
                continue
            trade_id = "bitunix:" + str(
                raw.get("position_id") or f"{symbol}:{closed_at}"
            )
            if trade_id in recorded_ids:
                continue
            close_event = {
                "type": "closed",
                "symbol": symbol,
                "timestamp": closed_at,
                "closed_at": closed_at,
                "exit": raw.get("close_price") or raw.get("exit") or raw.get("price"),
                "realized_pnl": raw.get("net_pnl", raw.get("realized_pnl", 0.0)),
                "close_reason": raw.get("reason") or "exchange_closed",
                "position": position,
            }
            entry_obs = self._find_entry_observation(symbol, position)
            exit_obs = self._find_exit_observation(symbol, close_event)
            record = build_trade_record_from_dicts(
                trade_id=trade_id,
                position=position,
                close_event=close_event,
                entry_observation=entry_obs.to_dict() if entry_obs else None,
                exit_observation=exit_obs.to_dict() if exit_obs else None,
            )
            self._learning.record_trade(record)
            recorded_ids.add(trade_id)
            new_recorded.append(trade_id)
        self._save_checkpoint({"recorded_trade_ids": sorted(recorded_ids)})
        return new_recorded

    @staticmethod
    def _normalize_bitunix_position(raw: dict[str, Any]) -> dict[str, Any]:
        compact = str(raw.get("symbol") or "").upper().replace("-", "")
        symbol = (
            f"{compact[:-4]}/USDT"
            if compact.endswith("USDT") and "/" not in compact
            else str(raw.get("symbol") or "")
        )
        side = "SELL" if str(raw.get("side") or "").upper() in {"SHORT", "SELL"} else "BUY"
        return {
            "symbol": symbol,
            "side": side,
            "entry": raw.get("entry_price") or raw.get("entry") or 0.0,
            "exit": raw.get("close_price") or raw.get("exit") or raw.get("price") or 0.0,
            "size": raw.get("quantity") or 0.0,
            "opened_at": raw.get("opened_at") or "",
            "closed_at": raw.get("closed_at") or raw.get("update_time") or "",
            "realized_pnl": raw.get("net_pnl", raw.get("realized_pnl", 0.0)),
            "stop_loss": raw.get("stop_loss") or 0.0,
            # TradeStore deserializes TP1 as float; use a neutral numeric
            # value when the exchange history does not return the TP ladder.
            "take_profit": [0.0, 0.0, 0.0],
            "confidence": 0.0,
            "strategy": "bitunix_live",
        }

    def _build_trade_id(
        self, symbol: str, position: dict[str, Any], event: dict[str, Any]
    ) -> str:
        opened = str(position.get("opened_at", ""))
        closed = str(event.get("timestamp") or position.get("closed_at", ""))
        return f"{symbol}:{opened}:{closed}"

    def _find_entry_observation(
        self, symbol: str, position: dict[str, Any]
    ) -> ChartObservation | None:
        candidates, _ = self._observations.load_latest(
            50, stage="ENTRY_CANDIDATE", symbol=symbol
        )
        if not candidates:
            return None
        opened_at = str(position.get("opened_at", ""))
        if not opened_at:
            return candidates[0]
        # Find latest ENTRY_CANDIDATE at or before position open time.
        eligible = [obs for obs in candidates if obs.timestamp <= opened_at]
        return eligible[-1] if eligible else candidates[0]

    def _find_exit_observation(
        self, symbol: str, event: dict[str, Any]
    ) -> ChartObservation | None:
        candidates, _ = self._observations.load_latest(
            50, stage="POSITION_MONITOR", symbol=symbol
        )
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
