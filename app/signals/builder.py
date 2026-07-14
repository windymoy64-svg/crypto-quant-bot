from __future__ import annotations

from app.core.models import Candle, ScoreResult, TradingSignal
from app.indicators.technical import atr
from app.indicators.structure import (
    find_nearest_resistance,
    find_nearest_support,
    find_swing_high,
    find_swing_low,
)

def _price_decimals(price: float) -> int:
    """Pembulatan adaptif berdasarkan magnitudo harga."""
    p = abs(price)
    if p >= 1000: return 2
    if p >= 100:  return 3
    if p >= 1:    return 4
    if p >= 0.01: return 6
    return 8

def build_signal(symbol: str, candles: list[Candle], score: ScoreResult) -> TradingSignal:
    entry = candles[-1].close
    current_atr = atr(candles)
    decimals = _price_decimals(entry)
    
    # SL: Structure-based with ATR buffer
    swing_low = find_swing_low(candles, lookback=10)
    if swing_low and swing_low < entry:
        # Place SL below swing low with 0.5×ATR buffer
        stop_loss = round(swing_low - (current_atr * 0.5), decimals)
    else:
        # Fallback: ATR-based if no structure found
        minimum_stop_distance = entry * 0.003
        stop_distance = max(current_atr * 1.5, minimum_stop_distance)
        stop_loss = round(entry - stop_distance, decimals)
    
    # TP: Resistance-based with ATR fallback, RR minimum 1:2
    risk_per_unit = entry - stop_loss
    min_tp1_distance = risk_per_unit * 2.0  # Force 1:2 RR minimum
    
    # TP1: Nearest resistance or 2R
    resistance = find_nearest_resistance(candles, entry, lookback=30)
    if resistance and resistance >= entry + min_tp1_distance:
        tp1 = round(resistance, decimals)
    else:
        tp1 = round(entry + min_tp1_distance, decimals)
    
    # TP2 & TP3: ATR extensions from TP1
    tp2 = round(tp1 + (current_atr * 1.5), decimals)
    tp3 = round(tp1 + (current_atr * 3.0), decimals)
    
    take_profit = [tp1, tp2, tp3]
    reward_per_unit = take_profit[0] - entry  # Use TP1 for RR calc
    risk_reward = round(reward_per_unit / risk_per_unit, 2) if risk_per_unit else 0.0
    risk = "LOW" if score.confidence >= 90 and risk_reward >= 2.0 else "MEDIUM" if score.confidence >= 80 else "HIGH"

    # Hitung gate dan failed_gates SEBELUM return
    gates = score.buckets.get("_gates", {}) if isinstance(score.buckets, dict) else {}
    failed_gates = [cat for cat, info in gates.items() if isinstance(info, dict) and not info.get("passed")]
    meta = {
        "max_score": score.max_score,
        "buckets": {k: v for k, v in score.buckets.items() if not str(k).startswith("_")},
        "gates": gates,
        "failed_gates": failed_gates,
        "raw_confidence": score.buckets.get("_raw_confidence"),
        "risk_fails": score.buckets.get("_risk_fails"),
        "passed_rules": [rule.rule_id for rule in score.rules if rule.passed],
        "failed_rules": [rule.rule_id for rule in score.rules if not rule.passed],
    }

    return TradingSignal(
        symbol=symbol,
        action=score.action,
        score=score.total_score,
        confidence=score.confidence,
        entry=round(entry, decimals),
        stop_loss=stop_loss,
        take_profit=take_profit,
        risk_reward=risk_reward,
        risk=risk,
        strategy="Weighted Rule Engine",
        meta=meta,
    )
    
def build_short_signal(
    symbol: str,
    candles: list[Candle],
    score: ScoreResult,
) -> TradingSignal:
    """Build SHORT signal with structure-based SL/TP."""

    entry = candles[-1].close
    current_atr = atr(candles)
    decimals = _price_decimals(entry)

    # SL: Structure-based with ATR buffer
    swing_high = find_swing_high(candles, lookback=10)
    if swing_high and swing_high > entry:
        # Place SL above swing high with 0.5×ATR buffer
        stop_loss = round(swing_high + (current_atr * 0.5), decimals)
    else:
        # Fallback: ATR-based if no structure found
        minimum_stop_distance = entry * 0.003
        stop_distance = max(current_atr * 1.5, minimum_stop_distance)
        stop_loss = round(entry + stop_distance, decimals)
    
    # TP: Support-based with ATR fallback, RR minimum 1:2
    risk_per_unit = stop_loss - entry
    min_tp1_distance = risk_per_unit * 2.0  # Force 1:2 RR minimum
    
    # TP1: Nearest support or 2R
    support = find_nearest_support(candles, entry, lookback=30)
    if support and support <= entry - min_tp1_distance:
        tp1 = round(support, decimals)
    else:
        tp1 = round(entry - min_tp1_distance, decimals)
    
    # TP2 & TP3: ATR extensions from TP1
    tp2 = round(tp1 - (current_atr * 1.5), decimals)
    tp3 = round(tp1 - (current_atr * 3.0), decimals)
    
    take_profit = [tp1, tp2, tp3]
    reward_per_unit = entry - take_profit[0]  # Use TP1 for RR calc
    risk_reward = (
        round(reward_per_unit / risk_per_unit, 2)
        if risk_per_unit > 0
        else 0.0
    )

    risk = (
        "LOW"
        if score.confidence >= 90 and risk_reward >= 2.0
        else "MEDIUM"
        if score.confidence >= 80
        else "HIGH"
    )

    gates = (
        score.buckets.get("_gates", {})
        if isinstance(score.buckets, dict)
        else {}
    )
    failed_gates = [
        category
        for category, info in gates.items()
        if isinstance(info, dict) and not info.get("passed")
    ]

    meta = {
        "direction": "SHORT",
        "max_score": score.max_score,
        "buckets": {
            key: value
            for key, value in score.buckets.items()
            if not str(key).startswith("_")
        },
        "gates": gates,
        "failed_gates": failed_gates,
        "raw_confidence": score.buckets.get("_raw_confidence"),
        "risk_fails": score.buckets.get("_risk_fails"),
        "passed_rules": [
            rule.rule_id for rule in score.rules if rule.passed
        ],
        "failed_rules": [
            rule.rule_id for rule in score.rules if not rule.passed
        ],
    }

    return TradingSignal(
        symbol=symbol,
        action="SELL" if score.action == "BUY" else score.action,
        score=score.total_score,
        confidence=score.confidence,
        entry=round(entry, decimals),
        stop_loss=stop_loss,
        take_profit=take_profit,
        risk_reward=risk_reward,
        risk=risk,
        strategy="Weighted Bearish Rule Engine",
        meta=meta,
    )