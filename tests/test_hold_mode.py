"""Trend-hold mode: skip fixed TP ladder until HTF structure flips."""

from __future__ import annotations

import json
from pathlib import Path

from app.decision_agent.agent import DecisionMakerAgent, is_trend_hold_mode
from app.paper.realtime_engine import PaperTradingConfig, RealtimePaperTradingEngine
from tests.test_decision_agent import _reading


def test_entry_sets_hold_meta_on_strong_trend() -> None:
    d = DecisionMakerAgent().decide_entry(_reading(confluence=75.0, aligned=True))
    assert d.action == "ENTRY_BUY"
    assert d.meta.get("hold_mode") is True
    assert d.meta.get("skip_fixed_tp") is True
    assert d.meta.get("tp1_enabled") is False


def test_entry_keeps_tp1_when_structure_weak() -> None:
    d = DecisionMakerAgent().decide_entry(
        _reading(confluence=75.0, aligned=False)
    )
    # misaligned → not hold mode (may still ENTRY or SKIP depending score)
    if d.action.startswith("ENTRY"):
        assert d.meta.get("tp1_enabled") is True
        assert d.meta.get("hold_mode") is False


def test_is_trend_hold_mode_matches_tp1_flag() -> None:
    strong = _reading(confluence=75.0, aligned=True)
    weak = _reading(confluence=75.0, aligned=False)
    assert is_trend_hold_mode(strong, "BUY") is True
    assert is_trend_hold_mode(weak, "BUY") is False


def test_paper_hold_mode_does_not_close_on_tp1(tmp_path: Path) -> None:
    cfg = PaperTradingConfig(
        enabled=True,
        starting_balance=10_000,
        risk_percent=1,
        max_open_positions=5,
        state_path=str(tmp_path / "s.json"),
        trades_path=str(tmp_path / "t.jsonl"),
    )
    eng = RealtimePaperTradingEngine(cfg)
    eng.process_signals(
        [
            {
                "symbol": "BTC/USDT",
                "action": "BUY",
                "entry": 100.0,
                "stop_loss": 97.0,
                "take_profit": [106.0, 109.0, 112.0],
                "confidence": 90.0,
                "tp1_enabled": False,
                "hold_mode": True,
                "skip_fixed_tp": True,
            }
        ]
    )
    # Price hits TP1 — must NOT partial or full close.
    eng.process_signals(
        [
            {
                "symbol": "BTC/USDT",
                "action": "BUY",
                "entry": 106.0,
                "stop_loss": 97.0,
                "take_profit": [106.0, 109.0, 112.0],
                "confidence": 90.0,
            }
        ]
    )
    state = json.loads(Path(cfg.state_path).read_text(encoding="utf-8"))
    pos = state["open_positions"]["BTC/USDT"]
    assert float(pos["remaining_size"]) == float(pos["size"])
    assert pos.get("skip_fixed_tp") is True


def test_paper_hold_mode_breakeven_after_1r(tmp_path: Path) -> None:
    cfg = PaperTradingConfig(
        enabled=True,
        starting_balance=10_000,
        risk_percent=1,
        max_open_positions=5,
        state_path=str(tmp_path / "s.json"),
        trades_path=str(tmp_path / "t.jsonl"),
    )
    eng = RealtimePaperTradingEngine(cfg)
    eng.process_signals(
        [
            {
                "symbol": "BTC/USDT",
                "action": "BUY",
                "entry": 100.0,
                "stop_loss": 97.0,  # risk = 3
                "take_profit": [106.0, 109.0, 112.0],
                "confidence": 90.0,
                "tp1_enabled": False,
                "hold_mode": True,
                "skip_fixed_tp": True,
            }
        ]
    )
    # +1R = price 103
    eng.process_signals(
        [
            {
                "symbol": "BTC/USDT",
                "action": "BUY",
                "entry": 103.0,
                "stop_loss": 97.0,
                "take_profit": [106.0, 109.0, 112.0],
                "confidence": 90.0,
            }
        ]
    )
    state = json.loads(Path(cfg.state_path).read_text(encoding="utf-8"))
    pos = state["open_positions"]["BTC/USDT"]
    assert float(pos["static_stop_loss"]) == 100.0
    assert pos.get("trailing_active") is True
