"""Tests for Learning Agent trade feedback and recorder."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.chart_agent.models import (
    CandlePatternDetection,
    ChartReading,
    KeyLevel,
)
from app.learning_agent.agent import LearningAgent
from app.learning_agent.feedback import (
    build_trade_record,
    build_trade_record_from_dicts,
)
from app.learning_agent.models import ChartObservation
from app.learning_agent.recorder import TradeFeedbackRecorder
from app.learning_agent.store import ChartObservationStore, TradeStore


def _reading() -> ChartReading:
    return ChartReading(
        symbol="BTC/USDT", timestamp="2024-01-01T10:00:00Z",
        bias="BULLISH", bias_confidence=80.0, confluence_score=75.0,
        regime="TRENDING_BULLISH", regime_confidence=70.0,
        htf_trend="UP", mtf_trend="UP", ltf_trend="UP", trends_aligned=True,
        candle_patterns=[
            CandlePatternDetection(
                name="morning_star", direction="BULLISH", strength="STRONG",
                candle_count=3, start_index=0, end_index=2, reliability=70.0,
                description="test",
            ),
        ],
        structure_breaks=[], order_blocks=[],
        key_levels=[
            KeyLevel(price=100.0, kind="support", strength="STRONG", source="test"),
        ],
        technique_signals=[], narrative="test", reasons=["test"],
        suggested_bias="BULLISH", entry_zone=(99.0, 101.0),
        invalidation_level=97.0,
        techniques_used=["acr_plus", "momentum"], meta={},
    )


def _position() -> dict[str, Any]:
    return {
        "symbol": "BTC/USDT",
        "side": "BUY",
        "entry": 100.0,
        "size": 2.0,
        "static_stop_loss": 97.0,
        "take_profit": [106.0, 109.0, 112.0],
        "opened_at": "2024-01-01T10:00:00+00:00",
        "highest_price": 108.0,
        "lowest_price": 98.5,
        "confidence": 92.0,
    }


def _write_trade_event(path: Path, event: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(event) + "\n")


def test_build_trade_record_from_reading() -> None:
    record = build_trade_record(
        trade_id="test-1",
        position=_position(),
        close_event={
            "type": "closed", "symbol": "BTC/USDT",
            "close_reason": "take_profit_1",
            "timestamp": "2024-01-01T14:00:00+00:00",
            "position": {"exit": 106.0, "realized_pnl": 12.0},
        },
        entry_reading=_reading(),
        exit_reading=_reading(),
    )
    assert record.symbol == "BTC/USDT"
    assert record.outcome == "TP"
    assert record.entry_price == 100.0
    assert "morning_star" in record.patterns_at_entry
    assert record.hold_duration_minutes == 240.0


def test_build_trade_record_classifies_stop_loss() -> None:
    record = build_trade_record(
        trade_id="test-sl", position=_position(),
        close_event={
            "close_reason": "stop_loss",
            "position": {"exit": 97.0, "realized_pnl": -6.0},
            "timestamp": "2024-01-01T12:00:00+00:00",
        },
        entry_reading=_reading(), exit_reading=_reading(),
    )
    assert record.outcome == "SL"
    assert record.pnl_absolute == -6.0


def test_build_trade_record_classifies_trailing() -> None:
    record = build_trade_record(
        trade_id="test-tr", position=_position(),
        close_event={
            "close_reason": "trailing_stop_hit",
            "position": {"exit": 105.0, "realized_pnl": 10.0},
            "timestamp": "2024-01-01T13:00:00+00:00",
        },
        entry_reading=_reading(), exit_reading=_reading(),
    )
    assert record.outcome == "TRAILING"


def test_build_trade_record_classifies_invalidation() -> None:
    record = build_trade_record(
        trade_id="test-inv", position=_position(),
        close_event={
            "close_reason": "counter_choch_detected",
            "position": {"exit": 99.5, "realized_pnl": -1.0},
            "timestamp": "2024-01-01T11:00:00+00:00",
        },
        entry_reading=_reading(), exit_reading=_reading(),
    )
    assert record.outcome == "INVALIDATION"


def test_build_trade_record_from_observation_dict() -> None:
    reading_dict = _reading().to_dict()
    record = build_trade_record_from_dicts(
        trade_id="obs-1",
        position=_position(),
        close_event={
            "close_reason": "take_profit_1",
            "position": {"exit": 106.0, "realized_pnl": 12.0},
            "timestamp": "2024-01-01T14:00:00+00:00",
        },
        entry_observation={"chart_reading": reading_dict},
        exit_observation={"chart_reading": reading_dict},
    )
    assert record.outcome == "TP"
    assert "morning_star" in record.patterns_at_entry
    assert record.regime_at_entry == "TRENDING_BULLISH"


def test_build_trade_record_missing_observation_uses_neutral_context() -> None:
    record = build_trade_record_from_dicts(
        trade_id="obs-2", position=_position(),
        close_event={
            "close_reason": "manual_close",
            "position": {"exit": 101.0, "realized_pnl": 2.0},
        },
        entry_observation=None, exit_observation=None,
    )
    assert record.regime_at_entry == "MIXED"
    assert record.bias_at_entry == "NEUTRAL"
    assert record.patterns_at_entry == []


def test_recorder_processes_new_closures(tmp_path: Path) -> None:
    trades = tmp_path / "paper_trades.jsonl"
    obs_store = ChartObservationStore(str(tmp_path / "obs.jsonl"))
    obs_store.save(ChartObservation(
        observation_id="BTC/USDT:2024-01-01T10:00:00Z:ENTRY_CANDIDATE",
        symbol="BTC/USDT", timestamp="2024-01-01T09:59:00+00:00",
        stage="ENTRY_CANDIDATE", scanner_confidence=95.0,
        scanner_gates_passed=True, chart_reading=_reading().to_dict(),
    ))
    _write_trade_event(trades, {
        "type": "closed",
        "symbol": "BTC/USDT",
        "timestamp": "2024-01-01T12:00:00+00:00",
        "close_reason": "take_profit_1",
        "position": {
            **_position(),
            "exit": 106.0,
            "realized_pnl": 12.0,
            "closed_at": "2024-01-01T12:00:00+00:00",
        },
    })

    trade_store = TradeStore(str(tmp_path / "trades.jsonl"))
    learning = LearningAgent(store=trade_store, observation_store=obs_store)
    recorder = TradeFeedbackRecorder(
        trades_path=str(trades),
        learning_agent=learning,
        observation_store=obs_store,
        checkpoint_path=str(tmp_path / "checkpoint.json"),
    )

    recorded = recorder.process_new_closures()
    assert len(recorded) == 1

    stored = trade_store.load_all()
    assert len(stored) == 1
    assert stored[0].outcome == "TP"
    assert stored[0].regime_at_entry == "TRENDING_BULLISH"
    assert "morning_star" in stored[0].patterns_at_entry


def test_recorder_is_idempotent(tmp_path: Path) -> None:
    trades = tmp_path / "paper_trades.jsonl"
    _write_trade_event(trades, {
        "type": "closed", "symbol": "BTC/USDT",
        "timestamp": "2024-01-01T12:00:00+00:00",
        "close_reason": "stop_loss",
        "position": {
            **_position(), "exit": 97.0, "realized_pnl": -6.0,
            "closed_at": "2024-01-01T12:00:00+00:00",
        },
    })

    trade_store = TradeStore(str(tmp_path / "trades.jsonl"))
    obs_store = ChartObservationStore(str(tmp_path / "obs.jsonl"))
    recorder = TradeFeedbackRecorder(
        trades_path=str(trades),
        learning_agent=LearningAgent(store=trade_store, observation_store=obs_store),
        observation_store=obs_store,
        checkpoint_path=str(tmp_path / "checkpoint.json"),
    )
    assert len(recorder.process_new_closures()) == 1
    # Second call should not re-record the same trade
    assert recorder.process_new_closures() == []
    assert len(trade_store.load_all()) == 1


def test_recorder_never_materializes_all_chart_observations(tmp_path: Path) -> None:
    """Large observation history must be queried with bounded load_latest()."""
    trades = tmp_path / "paper_trades.jsonl"
    obs_store = ChartObservationStore(str(tmp_path / "obs.jsonl"))
    obs_store.save(ChartObservation(
        observation_id="BTC:entry", symbol="BTC/USDT",
        timestamp="2024-01-01T09:59:00+00:00", stage="ENTRY_CANDIDATE",
        scanner_confidence=95.0, scanner_gates_passed=True,
        chart_reading=_reading().to_dict(),
    ))
    _write_trade_event(trades, {
        "type": "closed", "symbol": "BTC/USDT",
        "timestamp": "2024-01-01T12:00:00+00:00",
        "close_reason": "take_profit_1",
        "position": {**_position(), "exit": 106.0, "realized_pnl": 12.0},
    })
    # Regression guard: the old implementation called this and parsed the
    # complete ~200 MB production file into nested Python objects every cycle.
    obs_store.load_all = lambda: (_ for _ in ()).throw(AssertionError("unbounded load_all called"))  # type: ignore[method-assign]
    trade_store = TradeStore(str(tmp_path / "journal.jsonl"))
    recorder = TradeFeedbackRecorder(
        trades_path=str(trades),
        learning_agent=LearningAgent(store=trade_store, observation_store=obs_store),
        observation_store=obs_store,
        checkpoint_path=str(tmp_path / "checkpoint.json"),
    )
    assert len(recorder.process_new_closures()) == 1


def test_recorder_ignores_non_close_events(tmp_path: Path) -> None:
    trades = tmp_path / "paper_trades.jsonl"
    _write_trade_event(trades, {"type": "opened", "symbol": "BTC/USDT"})
    _write_trade_event(trades, {"type": "partial_close", "symbol": "BTC/USDT"})

    trade_store = TradeStore(str(tmp_path / "trades.jsonl"))
    obs_store = ChartObservationStore(str(tmp_path / "obs.jsonl"))
    recorder = TradeFeedbackRecorder(
        trades_path=str(trades),
        learning_agent=LearningAgent(store=trade_store, observation_store=obs_store),
        observation_store=obs_store,
        checkpoint_path=str(tmp_path / "checkpoint.json"),
    )
    assert recorder.process_new_closures() == []
    assert trade_store.load_all() == []
