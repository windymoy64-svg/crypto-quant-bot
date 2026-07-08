from __future__ import annotations

from app.core.models import Candle


def closes(candles: list[Candle]) -> list[float]:
    return [candle.close for candle in candles]


def volumes(candles: list[Candle]) -> list[float]:
    return [candle.volume for candle in candles]


def sma(values: list[float], period: int) -> float:
    if len(values) < period:
        return sum(values) / len(values)
    return sum(values[-period:]) / period


def ema(values: list[float], period: int) -> float:
    if not values:
        raise ValueError("values cannot be empty")
    multiplier = 2 / (period + 1)
    current = values[0]
    for value in values[1:]:
        current = (value * multiplier) + (current * (1 - multiplier))
    return current


def rsi(values: list[float], period: int = 14) -> float:
    if len(values) <= period:
        return 50.0
    gains: list[float] = []
    losses: list[float] = []
    for previous, current in zip(values[-period - 1 : -1], values[-period:]):
        change = current - previous
        gains.append(max(change, 0.0))
        losses.append(abs(min(change, 0.0)))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    relative_strength = avg_gain / avg_loss
    return 100 - (100 / (1 + relative_strength))


def atr(candles: list[Candle], period: int = 14) -> float:
    if len(candles) < 2:
        return 0.0
    ranges: list[float] = []
    recent = candles[-period:] if len(candles) >= period else candles
    previous_close = candles[-len(recent) - 1].close if len(candles) > len(recent) else recent[0].close
    for candle in recent:
        true_range = max(
            candle.high - candle.low,
            abs(candle.high - previous_close),
            abs(candle.low - previous_close),
        )
        ranges.append(true_range)
        previous_close = candle.close
    return sum(ranges) / len(ranges)


def macd(values: list[float]) -> dict[str, float]:
    fast = ema(values, 12)
    slow = ema(values, 26)
    line = fast - slow
    signal = line * 0.8
    histogram = line - signal
    return {"line": line, "signal": signal, "histogram": histogram}


def volume_ratio(candles: list[Candle], period: int = 20) -> float:
    values = volumes(candles)
    baseline = sma(values[:-1], min(period, max(len(values) - 1, 1))) if len(values) > 1 else values[-1]
    return values[-1] / baseline if baseline else 1.0
