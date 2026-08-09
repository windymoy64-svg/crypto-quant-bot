from __future__ import annotations

from app.chart_agent.models import StructureBreak
from app.chart_agent.momentum_phase import detect_momentum_phase
from app.core.models import Candle


def _candles(last_volume: float = 2_000.0) -> list[Candle]:
    candles = [
        Candle("BTC/USDT", str(index), 100 + index, 101 + index, 99 + index, 100 + index, 1_000)
        for index in range(30)
    ]
    candles[-1] = Candle("BTC/USDT", "29", 129, 132, 128, 131, last_volume)
    return candles


def _break(index: int, price: float = 130.0) -> StructureBreak:
    return StructureBreak("BOS", "BULLISH", price, index, str(index), index - 2)


def test_initial_break_is_detected_from_latest_candle() -> None:
    phase = detect_momentum_phase(_candles(), [_break(29)], "BULLISH")
    assert phase.phase == "initial"
    assert phase.break_age_bars == 0


def test_extended_break_is_not_fresh() -> None:
    phase = detect_momentum_phase(_candles(), [_break(20, 105.0)], "BULLISH")
    assert phase.phase == "extended"
    assert phase.extension_atr is not None
    assert phase.extension_atr > 1.25


def test_missing_volume_fails_closed() -> None:
    phase = detect_momentum_phase(_candles(last_volume=0.0), [_break(28, 130.0)], "BULLISH")
    assert phase.phase == "consolidating"
    assert phase.volume_ratio == 0.0
