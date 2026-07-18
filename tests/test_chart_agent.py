"""Tests for Chart Reader Agent."""

from __future__ import annotations

from app.core.models import Candle
from app.chart_agent.agent import ChartReaderAgent
from app.chart_agent.candle_patterns import detect_all_patterns
from app.chart_agent.structure_reader import (
    detect_order_blocks,
    detect_structure_breaks,
)
from app.chart_agent.confluence_engine import (
    calculate_confluence,
    get_regime_weight,
    meets_confluence_threshold,
)
from app.chart_agent.models import TechniqueSignal


def _c(i: int, o: float, h: float, l: float, c: float, v: float = 100.0) -> Candle:
    return Candle(symbol="BTC/USDT", timestamp=f"2024-01-01T{i:02d}:00:00Z",
                  open=o, high=h, low=l, close=c, volume=v)


def _uptrend_candles(n: int = 30) -> list[Candle]:
    candles = []
    base = 100.0
    for i in range(n):
        o = base + i * 1.0
        c = o + 0.8
        h = c + 0.3
        l = o - 0.2
        candles.append(_c(i, o, h, l, c))
    return candles


def _downtrend_candles(n: int = 30) -> list[Candle]:
    candles = []
    base = 200.0
    for i in range(n):
        o = base - i * 1.0
        c = o - 0.8
        h = o + 0.2
        l = c - 0.3
        candles.append(_c(i, o, h, l, c))
    return candles


# ---------------------------------------------------------------------------
# Candle pattern tests
# ---------------------------------------------------------------------------


def test_detect_bullish_engulfing() -> None:
    candles = [
        _c(0, 105, 106, 100, 101),  # bearish
        _c(1, 100, 108, 99, 107),   # bullish engulfing
    ]
    patterns = detect_all_patterns(candles)
    names = [p.name for p in patterns]
    assert "bullish_engulfing" in names


def test_detect_hammer() -> None:
    # Hammer: body ~1.0, lower wick ~4.0, upper wick ~0.5
    # body_ratio = 1/5.5 = 0.18 (within 0.10-0.35), lower_wick >= 2*body, upper <= 0.5*body
    candles = [
        _c(0, 100, 101, 99, 100.5),
        _c(1, 99, 100.5, 95, 100),  # body=1, lw=4, uw=0.5, range=5.5
    ]
    patterns = detect_all_patterns(candles)
    names = [p.name for p in patterns]
    assert "hammer" in names


def test_detect_doji() -> None:
    candles = [_c(0, 100, 105, 95, 100.1)]
    patterns = detect_all_patterns(candles)
    names = [p.name for p in patterns]
    assert "doji" in names


def test_detect_morning_star() -> None:
    candles = [
        _c(0, 110, 111, 104, 105),
        _c(1, 105, 105.5, 104, 104.5),
        _c(2, 105, 112, 104.5, 111),
    ]
    patterns = detect_all_patterns(candles)
    names = [p.name for p in patterns]
    assert "morning_star" in names


def test_detect_three_white_soldiers() -> None:
    candles = [
        _c(0, 100, 103, 99.5, 102.5),
        _c(1, 103, 106, 102.5, 105.5),
        _c(2, 106, 109, 105.5, 108.5),
    ]
    patterns = detect_all_patterns(candles)
    names = [p.name for p in patterns]
    assert "three_white_soldiers" in names


def test_no_patterns_on_empty() -> None:
    assert detect_all_patterns([]) == []


# ---------------------------------------------------------------------------
# Structure reader tests
# ---------------------------------------------------------------------------


def test_structure_breaks_uptrend() -> None:
    # Need candles with actual swing points (pullbacks) to form fractals
    candles = [
        _c(0, 100, 102, 99, 101),
        _c(1, 101, 104, 100, 103),   # swing high candidate
        _c(2, 103, 103.5, 100, 101),  # pullback -> confirms c1 as swing high
        _c(3, 101, 102, 99, 100),     # lower
        _c(4, 100, 100.5, 97, 98),    # swing low candidate
        _c(5, 98, 101, 97.5, 100),    # bounce -> confirms c4 as swing low
        _c(6, 100, 103, 99, 102),
        _c(7, 102, 106, 101, 105),    # breaks swing high at 104 -> BOS bullish
        _c(8, 105, 107, 104, 106),
        _c(9, 106, 108, 105, 107),
    ]
    breaks = detect_structure_breaks(candles, swing_lookback=8)
    bullish_breaks = [b for b in breaks if b.direction == "BULLISH"]
    assert len(bullish_breaks) >= 1


def test_order_blocks_detected() -> None:
    candles = [
        _c(0, 100, 101, 99, 100.5),
        _c(1, 100.5, 101, 100, 100.2),
        _c(2, 100.2, 100.5, 99.5, 99.8),  # bearish
        _c(3, 99.8, 100, 99, 99.2),
        _c(4, 99.2, 106, 99, 105.5),       # displacement
        _c(5, 105.5, 107, 105, 106.5),
    ]
    obs = detect_order_blocks(candles, min_displacement_ratio=0.8)
    bullish_obs = [ob for ob in obs if ob.direction == "BULLISH"]
    assert len(bullish_obs) >= 1


# ---------------------------------------------------------------------------
# Confluence engine tests
# ---------------------------------------------------------------------------


def test_confluence_all_bullish() -> None:
    signals = [
        TechniqueSignal("structure", "BULLISH", 80.0, 1.2, ["bos_bullish"]),
        TechniqueSignal("momentum", "BULLISH", 70.0, 1.0, ["ema_stack"]),
        TechniqueSignal("candle_patterns", "BULLISH", 65.0, 0.8, ["engulfing"]),
    ]
    bias, confidence, score = calculate_confluence(signals, "TRENDING_BULLISH")
    assert bias == "BULLISH"
    assert score == 100.0
    assert confidence > 50


def test_confluence_mixed_signals() -> None:
    signals = [
        TechniqueSignal("structure", "BULLISH", 70.0, 1.2, ["bos"]),
        TechniqueSignal("momentum", "BEARISH", 60.0, 1.0, ["macd_bear"]),
        TechniqueSignal("candle_patterns", "NEUTRAL", 40.0, 0.8, ["doji"]),
    ]
    bias, confidence, score = calculate_confluence(signals, "MIXED")
    assert score < 100.0


def test_regime_weight_trending() -> None:
    w = get_regime_weight("TRENDING_BULLISH", "momentum")
    assert w > 1.0


def test_regime_weight_ranging() -> None:
    w = get_regime_weight("RANGING", "order_blocks")
    assert w > 1.0


def test_meets_threshold() -> None:
    assert meets_confluence_threshold(80.0, "TRENDING_BULLISH") is True
    assert meets_confluence_threshold(40.0, "HIGH_VOLATILITY") is False


# ---------------------------------------------------------------------------
# Full agent integration test
# ---------------------------------------------------------------------------


def test_agent_read_produces_chart_reading() -> None:
    agent = ChartReaderAgent()
    htf = _uptrend_candles(30)
    mtf = _uptrend_candles(30)
    ltf = _uptrend_candles(30)

    reading = agent.read(
        symbol="BTC/USDT",
        htf_candles=htf,
        mtf_candles=mtf,
        ltf_candles=ltf,
    )

    assert reading.symbol == "BTC/USDT"
    assert reading.timestamp != ""
    assert reading.bias in ("BULLISH", "BEARISH", "NEUTRAL")
    assert 0 <= reading.bias_confidence <= 100
    assert 0 <= reading.confluence_score <= 100
    assert reading.htf_trend in ("UP", "DOWN", "SIDE")
    assert len(reading.techniques_used) >= 5
    assert isinstance(reading.narrative, str)
    assert len(reading.narrative) > 0

    d = reading.to_dict()
    assert isinstance(d, dict)
    assert d["symbol"] == "BTC/USDT"


def test_agent_read_downtrend() -> None:
    agent = ChartReaderAgent()
    htf = _downtrend_candles(30)
    mtf = _downtrend_candles(30)
    ltf = _downtrend_candles(30)

    reading = agent.read(
        symbol="ETH/USDT",
        htf_candles=htf,
        mtf_candles=mtf,
        ltf_candles=ltf,
    )

    assert reading.symbol == "ETH/USDT"
    assert reading.bias in ("BEARISH", "NEUTRAL")

