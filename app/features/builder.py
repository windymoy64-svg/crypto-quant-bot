from __future__ import annotations

from app.core.models import Candle
from app.indicators.technical import atr, closes, ema, macd, rsi, sma, volume_ratio


def _percent_change(current: float, previous: float) -> float:
    return ((current - previous) / previous) * 100 if previous else 0.0


def _safe_ratio(numerator: float, denominator: float, default: float = 0.0) -> float:
    return numerator / denominator if denominator else default


def _streak(values: list[float], *, rising: bool) -> int:
    streak = 0
    for previous, current in zip(reversed(values[:-1]), reversed(values[1:])):
        if (current > previous and rising) or (current < previous and not rising):
            streak += 1
            continue
        break
    return streak


def build_features(candles: list[Candle]) -> dict[str, float | bool]:
    if not candles:
        raise ValueError("candles cannot be empty")

    price_values = closes(candles)
    ema20 = ema(price_values, 20)
    ema50 = ema(price_values, 50)
    ema200 = ema(price_values, 200)
    ema9 = ema(price_values, 9)
    sma20 = sma(price_values, min(20, len(price_values)))
    sma50 = sma(price_values, min(50, len(price_values)))
    macd_values = macd(price_values)
    current_rsi = rsi(price_values)
    current_atr = atr(candles)
    atr_percent = (current_atr / price_values[-1]) * 100 if price_values[-1] else 0.0
    current_price = price_values[-1]
    previous_price = price_values[-2] if len(price_values) > 1 else current_price
    price_5_ago = price_values[-6] if len(price_values) > 5 else price_values[0]
    price_10_ago = price_values[-11] if len(price_values) > 10 else price_values[0]
    price_20_ago = price_values[-21] if len(price_values) > 20 else price_values[0]
    recent_5 = candles[-5:]
    recent_10 = candles[-10:]
    recent_high = max(candle.high for candle in candles[-20:])
    recent_low = min(candle.low for candle in candles[-20:])
    high_5 = max(candle.high for candle in recent_5)
    low_5 = min(candle.low for candle in recent_5)
    high_10 = max(candle.high for candle in recent_10)
    low_10 = min(candle.low for candle in recent_10)
    latest = candles[-1]
    body = latest.close - latest.open
    body_abs = abs(body)
    candle_range = latest.high - latest.low
    upper_wick = latest.high - max(latest.open, latest.close)
    lower_wick = min(latest.open, latest.close) - latest.low
    range_position = _safe_ratio(current_price - recent_low, recent_high - recent_low, 0.5)
    day_position_5 = _safe_ratio(current_price - low_5, high_5 - low_5, 0.5)
    day_position_10 = _safe_ratio(current_price - low_10, high_10 - low_10, 0.5)
    vol_ratio = volume_ratio(candles)
    previous_vol_ratio = _safe_ratio(latest.volume, candles[-2].volume, 1.0) if len(candles) > 1 else 1.0
    green_count_5 = sum(1 for candle in recent_5 if candle.close > candle.open)
    green_count_10 = sum(1 for candle in recent_10 if candle.close > candle.open)
    up_streak = _streak(price_values, rising=True)
    down_streak = _streak(price_values, rising=False)
    momentum_1 = _percent_change(current_price, previous_price)
    momentum_5 = _percent_change(current_price, price_5_ago)
    momentum_10 = _percent_change(current_price, price_10_ago)
    momentum_20 = _percent_change(current_price, price_20_ago)
    ema20_gap = _percent_change(current_price, ema20)
    ema50_gap = _percent_change(current_price, ema50)
    ema200_gap = _percent_change(current_price, ema200)
    ema_spread_20_50 = _percent_change(ema20, ema50)
    ema_spread_50_200 = _percent_change(ema50, ema200)
    volatility_5 = _safe_ratio(high_5 - low_5, current_price) * 100
    volatility_10 = _safe_ratio(high_10 - low_10, current_price) * 100
    breakout_distance = _percent_change(current_price, recent_high)
    support_distance = _percent_change(current_price, recent_low)

    return {
        "price": current_price,
        "previous_price": previous_price,
        "ema20": ema20,
        "ema50": ema50,
        "ema200": ema200,
        "ema9": ema9,
        "sma20": sma20,
        "sma50": sma50,
        "ema20_gap_percent": ema20_gap,
        "ema50_gap_percent": ema50_gap,
        "ema200_gap_percent": ema200_gap,
        "ema_spread_20_50_percent": ema_spread_20_50,
        "ema_spread_50_200_percent": ema_spread_50_200,
        "ema_stack_bullish": ema9 > ema20 > ema50,
        "ema20_gt_ema50": ema20 > ema50,
        "ema50_gt_ema200": ema50 > ema200,
        "ema9_gt_ema20": ema9 > ema20,
        "price_gt_ema9": current_price > ema9,
        "price_gt_ema20": current_price > ema20,
        "price_gt_ema50": current_price > ema50,
        "price_gt_ema200": current_price > ema200,
        "price_gt_sma20": current_price > sma20,
        "price_gt_sma50": current_price > sma50,
        "sma20_gt_sma50": sma20 > sma50,
        "macd_bullish": macd_values["line"] > macd_values["signal"],
        "macd_line": macd_values["line"],
        "macd_signal": macd_values["signal"],
        "macd_histogram": macd_values["histogram"],
        "rsi": current_rsi,
        "rsi_healthy_bullish": 50 <= current_rsi <= 75,
        "rsi_above_45": current_rsi >= 45,
        "rsi_above_50": current_rsi >= 50,
        "rsi_above_55": current_rsi >= 55,
        "rsi_below_65": current_rsi <= 65,
        "rsi_below_70": current_rsi <= 70,
        "rsi_below_80": current_rsi <= 80,
        "atr": current_atr,
        "atr_percent": atr_percent,
        "atr_above_0_2_percent": atr_percent >= 0.2,
        "atr_below_1_percent": atr_percent < 1.0,
        "atr_below_1_5_percent": atr_percent < 1.5,
        "atr_below_2_percent": atr_percent < 2.0,
        "atr_below_3_percent": atr_percent < 3.0,
        "volume_ratio": vol_ratio,
        "previous_volume_ratio": previous_vol_ratio,
        "volume_spike": vol_ratio >= 1.15,
        "volume_above_average": vol_ratio >= 1.0,
        "volume_ratio_gt_1_05": vol_ratio >= 1.05,
        "volume_ratio_gt_1_10": vol_ratio >= 1.10,
        "volume_ratio_gt_1_25": vol_ratio >= 1.25,
        "volume_vs_previous_gt_0_9": previous_vol_ratio >= 0.9,
        "volume_vs_previous_gt_1_0": previous_vol_ratio >= 1.0,
        "near_breakout": current_price >= recent_high * 0.99,
        "breakout_distance_percent": breakout_distance,
        "support_distance_percent": support_distance,
        "near_5_high": current_price >= high_5 * 0.99,
        "near_10_high": current_price >= high_10 * 0.99,
        "above_5_midpoint": current_price >= (high_5 + low_5) / 2,
        "above_10_midpoint": current_price >= (high_10 + low_10) / 2,
        "support_buffer_gt_0_5_percent": support_distance >= 0.5,
        "support_buffer_gt_1_percent": support_distance >= 1.0,
        "pullback_zone": ema20 <= current_price <= ema20 * 1.025,
        "range_position": range_position,
        "range_position_5": day_position_5,
        "range_position_10": day_position_10,
        "range_above_mid": range_position >= 0.5,
        "range_below_top": range_position <= 0.95,
        "range_5_above_mid": day_position_5 >= 0.5,
        "range_10_above_mid": day_position_10 >= 0.5,
        "momentum_1_percent": momentum_1,
        "momentum_5_percent": momentum_5,
        "momentum_10_percent": momentum_10,
        "momentum_20_percent": momentum_20,
        "momentum_1_positive": momentum_1 > 0,
        "momentum_5_positive": momentum_5 > 0,
        "momentum_10_positive": momentum_10 > 0,
        "momentum_20_positive": momentum_20 > 0,
        "momentum_5_gt_0_5": momentum_5 >= 0.5,
        "momentum_10_gt_1": momentum_10 >= 1.0,
        "momentum_20_gt_2": momentum_20 >= 2.0,
        "up_streak": float(up_streak),
        "down_streak": float(down_streak),
        "up_streak_ge_1": up_streak >= 1,
        "up_streak_ge_2": up_streak >= 2,
        "down_streak_le_1": down_streak <= 1,
        "green_count_5": float(green_count_5),
        "green_count_10": float(green_count_10),
        "green_count_5_ge_3": green_count_5 >= 3,
        "green_count_10_ge_6": green_count_10 >= 6,
        "latest_green": latest.close > latest.open,
        "latest_body_percent": _safe_ratio(body_abs, latest.open) * 100,
        "latest_range_percent": _safe_ratio(candle_range, latest.open) * 100,
        "latest_close_near_high": _safe_ratio(latest.close - latest.low, candle_range, 0.5) >= 0.65,
        "latest_lower_wick_gt_upper": lower_wick > upper_wick,
        "latest_body_gt_30_range": _safe_ratio(body_abs, candle_range) >= 0.30,
        "latest_range_below_2_atr": candle_range <= current_atr * 2 if current_atr else True,
        "volatility_5_percent": volatility_5,
        "volatility_10_percent": volatility_10,
        "volatility_5_below_3_percent": volatility_5 < 3.0,
        "volatility_10_below_5_percent": volatility_10 < 5.0,
    }
