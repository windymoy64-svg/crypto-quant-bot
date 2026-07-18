"""Tests for Learning Agent."""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.learning_agent.agent import LearningAgent
from app.learning_agent.models import TradeRecord, LearningInsight
from app.learning_agent.store import TradeStore


def _make_record(
    symbol: str = "BTC/USDT",
    side: str = "BUY",
    pnl: float = 2.0,
    outcome: str = "TP",
    regime: str = "TRENDING_BULLISH",
    patterns: list[str] | None = None,
    techniques: list[str] | None = None,
    confluence: float = 75.0,
    idx: int = 0,
) -> TradeRecord:
    return TradeRecord(
        trade_id=f"test_{idx}",
        symbol=symbol,
        side=side,
        timestamp_entry=f"2024-01-{idx+1:02d}T10:00:00Z",
        timestamp_exit=f"2024-01-{idx+1:02d}T12:00:00Z",
        entry_price=100.0,
        exit_price=100.0 + pnl if side == "BUY" else 100.0 - pnl,
        stop_loss=97.0,
        take_profit_1=103.0,
        outcome=outcome,
        pnl_percent=pnl,
        pnl_absolute=pnl * 10,
        hold_duration_minutes=120.0,
        regime_at_entry=regime,
        bias_at_entry="BULLISH" if pnl > 0 else "BEARISH",
        confluence_at_entry=confluence,
        htf_trend_at_entry="UP",
        patterns_at_entry=patterns or ["morning_star"],
        techniques_at_entry=techniques or ["acr_plus", "momentum"],
        entry_strategy="acr_plus",
        entry_confidence=92.0,
    )


def test_empty_learning() -> None:
    agent = LearningAgent(store=TradeStore(path="/tmp/_test_empty.jsonl"))
    insight = agent.learn()
    assert insight.total_trades == 0
    assert insight.overall_winrate == 0.0
    assert insight.min_confluence_recommended == 50.0


def test_learn_from_records() -> None:
    records = [
        _make_record(pnl=3.0, outcome="TP", confluence=80.0, idx=0),
        _make_record(pnl=2.5, outcome="TP", confluence=75.0, idx=1),
        _make_record(pnl=-1.5, outcome="SL", confluence=55.0, idx=2),
        _make_record(pnl=1.8, outcome="TRAILING", confluence=70.0, idx=3),
        _make_record(pnl=-2.0, outcome="SL", confluence=50.0, idx=4),
    ]
    agent = LearningAgent()
    insight = agent.learn_from(records)

    assert insight.total_trades == 5
    assert insight.overall_winrate == 60.0  # 3 wins / 5
    assert insight.overall_avg_pnl > 0
    assert insight.avg_confluence_winners > insight.avg_confluence_losers


def test_pattern_insights_computed() -> None:
    records = [
        _make_record(pnl=2.0, patterns=["engulfing"], regime="TRENDING_BULLISH", idx=i)
        for i in range(6)
    ] + [
        _make_record(pnl=-1.0, patterns=["engulfing"], regime="TRENDING_BULLISH", idx=i+6)
        for i in range(4)
    ]
    agent = LearningAgent()
    insight = agent.learn_from(records)

    eng_insights = [p for p in insight.pattern_insights if p.pattern_name == "engulfing"]
    assert len(eng_insights) == 1
    assert eng_insights[0].total_trades == 10
    assert eng_insights[0].winrate == 60.0
    assert eng_insights[0].is_reliable is True


def test_regime_insights() -> None:
    records = [
        _make_record(pnl=3.0, regime="TRENDING_BULLISH", idx=0),
        _make_record(pnl=2.0, regime="TRENDING_BULLISH", idx=1),
        _make_record(pnl=-1.0, regime="RANGING", idx=2),
        _make_record(pnl=-2.0, regime="RANGING", idx=3),
    ]
    agent = LearningAgent()
    insight = agent.learn_from(records)

    assert insight.best_regime == "TRENDING_BULLISH"
    assert insight.worst_regime == "RANGING"


def test_symbol_insights() -> None:
    records = [
        _make_record(symbol="BTC/USDT", pnl=3.0, idx=0),
        _make_record(symbol="BTC/USDT", pnl=2.0, idx=1),
        _make_record(symbol="ETH/USDT", pnl=-1.0, idx=2),
    ]
    agent = LearningAgent()
    insight = agent.learn_from(records)

    btc = [s for s in insight.symbol_insights if s.symbol == "BTC/USDT"]
    assert len(btc) == 1
    assert btc[0].winrate == 100.0


def test_store_save_and_load() -> None:
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
        path = f.name

    store = TradeStore(path=path)
    record = _make_record(pnl=5.0, idx=0)
    store.save(record)
    store.save(_make_record(pnl=-1.0, idx=1))

    loaded = store.load_all()
    assert len(loaded) == 2
    assert loaded[0].trade_id == "test_0"
    assert loaded[0].pnl_percent == 5.0
    assert loaded[1].pnl_percent == -1.0

    Path(path).unlink(missing_ok=True)


def test_hot_cold_patterns() -> None:
    # 7 wins out of 8 -> winrate 87.5% -> hot
    records = [
        _make_record(pnl=2.0, patterns=["three_white_soldiers"], idx=i)
        for i in range(7)
    ] + [
        _make_record(pnl=-1.0, patterns=["three_white_soldiers"], idx=7),
    ]
    # 1 win out of 6 -> winrate 16.7% -> cold
    records += [
        _make_record(pnl=-1.5, patterns=["doji"], idx=i+8)
        for i in range(5)
    ] + [
        _make_record(pnl=0.5, patterns=["doji"], idx=13),
    ]

    agent = LearningAgent()
    insight = agent.learn_from(records)

    assert "three_white_soldiers" in insight.hot_patterns
    assert "doji" in insight.cold_patterns


def test_to_dict() -> None:
    agent = LearningAgent()
    insight = agent.learn_from([_make_record(idx=0)])
    d = insight.to_dict()
    assert isinstance(d, dict)
    assert d["total_trades"] == 1
    assert "pattern_insights" in d
    assert "regime_insights" in d
