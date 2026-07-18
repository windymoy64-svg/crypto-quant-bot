"""Tests for Learning Agent runtime bootstrapper."""

from __future__ import annotations

from pathlib import Path

from app.learning_agent.recorder import TradeFeedbackRecorder
from app.learning_agent.runtime import (
    LearningRecorderConfig,
    build_recorder_if_enabled,
)


def test_config_defaults_disabled() -> None:
    cfg = LearningRecorderConfig.from_dict(None)
    assert cfg.enabled is False
    assert cfg.trade_store_path == "data/learning_journal.jsonl"


def test_config_reads_all_fields() -> None:
    cfg = LearningRecorderConfig.from_dict({
        "enabled": True,
        "trades_path": "custom/paper_trades.jsonl",
        "trade_store_path": "custom/journal.jsonl",
        "observation_store_path": "custom/obs.jsonl",
        "checkpoint_path": "custom/checkpoint.json",
    })
    assert cfg.enabled is True
    assert cfg.trades_path == "custom/paper_trades.jsonl"


def test_resolve_trades_path_prefers_explicit() -> None:
    cfg = LearningRecorderConfig.from_dict({"trades_path": "custom/path.jsonl"})
    assert cfg.resolve_trades_path("fallback/path.jsonl") == "custom/path.jsonl"


def test_resolve_trades_path_uses_fallback_when_empty() -> None:
    cfg = LearningRecorderConfig.from_dict({})
    assert cfg.resolve_trades_path("fallback/path.jsonl") == "fallback/path.jsonl"


def test_build_recorder_returns_none_when_disabled(tmp_path: Path) -> None:
    cfg = LearningRecorderConfig.from_dict({"enabled": False})
    assert build_recorder_if_enabled(cfg, paper_trades_path=str(tmp_path / "x")) is None


def test_build_recorder_returns_none_when_trades_file_missing(tmp_path: Path) -> None:
    cfg = LearningRecorderConfig.from_dict({
        "enabled": True,
        "trades_path": str(tmp_path / "missing.jsonl"),
    })
    assert build_recorder_if_enabled(cfg, paper_trades_path=None) is None


def test_build_recorder_uses_paper_trades_path_fallback(tmp_path: Path) -> None:
    paper_trades = tmp_path / "paper_trades.jsonl"
    paper_trades.write_text("", encoding="utf-8")
    cfg = LearningRecorderConfig.from_dict({
        "enabled": True,
        "trade_store_path": str(tmp_path / "journal.jsonl"),
        "observation_store_path": str(tmp_path / "obs.jsonl"),
        "checkpoint_path": str(tmp_path / "checkpoint.json"),
    })
    recorder = build_recorder_if_enabled(
        cfg, paper_trades_path=str(paper_trades)
    )
    assert isinstance(recorder, TradeFeedbackRecorder)


def test_build_recorder_processes_no_op_when_no_closures(tmp_path: Path) -> None:
    paper_trades = tmp_path / "paper_trades.jsonl"
    paper_trades.write_text("", encoding="utf-8")
    cfg = LearningRecorderConfig.from_dict({
        "enabled": True,
        "trade_store_path": str(tmp_path / "journal.jsonl"),
        "observation_store_path": str(tmp_path / "obs.jsonl"),
        "checkpoint_path": str(tmp_path / "checkpoint.json"),
    })
    recorder = build_recorder_if_enabled(
        cfg, paper_trades_path=str(paper_trades)
    )
    assert recorder is not None
    assert recorder.process_new_closures() == []
