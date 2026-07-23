"""Assert-based checks for structure + ATR level placement."""

from __future__ import annotations

from app.chart_agent.level_placement import (
    harden_invalidation,
    sl_passes_noise_floor,
    select_entry_invalidation,
)
from app.chart_agent.models import KeyLevel, OrderBlock, TechniqueSignal
from app.core.models import Candle
from app.decision_agent.agent import DecisionMakerAgent
from tests.test_decision_agent import _reading


def _candles(n: int = 40, base: float = 100.0) -> list[Candle]:
    out: list[Candle] = []
    for i in range(n):
        c = base + (i % 5) * 0.2
        out.append(
            Candle(
                symbol="BTC/USDT",
                timestamp=f"2024-01-01T{i:02d}:00:00Z",
                open=c,
                high=c + 0.8,
                low=c - 0.8,
                close=c + 0.1,
                volume=1000.0,
            )
        )
    return out


def test_noise_stop_rejected() -> None:
    assert not sl_passes_noise_floor(100.0, 99.8, 1.0)


def test_solid_stop_accepted() -> None:
    assert sl_passes_noise_floor(100.0, 98.5, 1.0)


def test_harden_puts_sl_beyond_structure() -> None:
    sl = harden_invalidation(
        bias="BULLISH", structure_edge=99.0, entry_ref=100.0, atr_value=1.0
    )
    assert sl is not None and sl < 99.0


def test_select_rejects_nearest_noise_ob() -> None:
    """OB with 0.2% haircut style edge must not win over solid swing."""
    liq = TechniqueSignal(
        technique="liquidity_sr_mtf",
        bias="BULLISH",
        confidence=0.0,
        weight=1.0,
        reasons=[],
        meta={},
    )
    # Tight OB near price (noise)
    tight_ob = OrderBlock(
        direction="BULLISH",
        top=99.9,
        bottom=99.7,
        index=10,
        timestamp="t",
        mitigated=False,
    )
    candles = _candles()
    # Force a deeper swing low via last lows
    for c in candles[-15:]:
        object.__setattr__(c, "low", 97.0) if False else None
    # rebuild candles with deep swing
    deep = []
    for i, c in enumerate(candles):
        low = 97.0 if i < 15 else c.low
        deep.append(
            Candle(
                symbol="BTC/USDT",
                timestamp=c.timestamp,
                open=c.open,
                high=c.high,
                low=low,
                close=c.close,
                volume=c.volume,
            )
        )
    zone, inval, source, meta = select_entry_invalidation(
        bias="BULLISH",
        current_price=100.5,
        atr_value=1.0,
        liq_signal=liq,
        obs=[tight_ob],
        key_levels=[
            KeyLevel(price=97.2, kind="support", strength="STRONG", source="swing_low")
        ],
        htf_candles=deep,
        mtf_candles=deep,
        ltf_candles=deep,
    )
    assert zone is not None
    assert inval is not None
    # Must clear ~0.8 ATR minimum → not a 0.2% haircut stop
    assert abs(100.5 - inval) / 100.5 * 100 >= 0.35
    assert meta.get("sl_atr", 0) >= 0.8 or meta.get("sl_pct", 0) >= 0.35


def test_decision_rejects_thin_sl() -> None:
    agent = DecisionMakerAgent()
    r = _reading(entry_zone=(99.9, 100.1), invalidation=99.85)
    assert agent._build_entry_plan(r) is None


def test_decision_plan_uses_rr_from_tp1() -> None:
    agent = DecisionMakerAgent()
    plan = agent._build_entry_plan(_reading())
    assert plan is not None
    assert plan.risk_reward >= 2.0
    assert plan.take_profit_1 > plan.entry_price
