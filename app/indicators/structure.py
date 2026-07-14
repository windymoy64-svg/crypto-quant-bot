from __future__ import annotations

from app.core.models import Candle


def find_swing_low(candles: list[Candle], lookback: int = 5) -> float | None:
    """Find most recent swing low within lookback period.
    Swing low = candle.low < both neighbors' lows."""
    if len(candles) < 3 or lookback < 3:
        return None
    
    window = candles[-lookback:]
    for i in range(len(window) - 2, 0, -1):  # scan backwards, skip edges
        if window[i].low < window[i-1].low and window[i].low < window[i+1].low:
            return window[i].low
    return None


def find_swing_high(candles: list[Candle], lookback: int = 5) -> float | None:
    """Find most recent swing high within lookback period.
    Swing high = candle.high > both neighbors' highs."""
    if len(candles) < 3 or lookback < 3:
        return None
    
    window = candles[-lookback:]
    for i in range(len(window) - 2, 0, -1):  # scan backwards, skip edges
        if window[i].high > window[i-1].high and window[i].high > window[i+1].high:
            return window[i].high
    return None


def find_nearest_resistance(candles: list[Candle], entry: float, lookback: int = 20) -> float | None:
    """Find nearest resistance level above entry.
    Uses swing highs from lookback period."""
    if len(candles) < lookback:
        return None
    
    window = candles[-lookback:]
    resistances = []
    
    for i in range(1, len(window) - 1):
        if window[i].high > window[i-1].high and window[i].high > window[i+1].high:
            if window[i].high > entry:
                resistances.append(window[i].high)
    
    return min(resistances) if resistances else None


def find_nearest_support(candles: list[Candle], entry: float, lookback: int = 20) -> float | None:
    """Find nearest support level below entry.
    Uses swing lows from lookback period."""
    if len(candles) < lookback:
        return None
    
    window = candles[-lookback:]
    supports = []
    
    for i in range(1, len(window) - 1):
        if window[i].low < window[i-1].low and window[i].low < window[i+1].low:
            if window[i].low < entry:
                supports.append(window[i].low)
    
    return max(supports) if supports else None
