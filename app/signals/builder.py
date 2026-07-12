from __future__ import annotations

from app.core.models import Candle, ScoreResult, TradingSignal
from app.indicators.technical import atr

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
    stop_loss = round(entry - (current_atr * 1.5), decimals)
    take_profit = [round(entry + (current_atr * multiple), decimals) for multiple in (1.5, 2.5, 3.5)]
    risk_per_unit = entry - stop_loss
    reward_per_unit = take_profit[1] - entry
    risk_reward = round(reward_per_unit / risk_per_unit, 2) if risk_per_unit else 0.0
    risk = "LOW" if score.confidence >= 90 and risk_reward >= 1.5 else "MEDIUM" if score.confidence >= 80 else "HIGH"

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
    """Membangun kandidat SHORT tanpa mengubah builder LONG."""

    entry = candles[-1].close
    current_atr = atr(candles)
    decimals = _price_decimals(entry)

    # SHORT: SL di atas entry, TP di bawah entry.
    # Jarak risiko wajib minimal 0,5% agar lolos proteksi sizing.
    atr_stop_distance = current_atr * 1.5
    minimum_stop_distance = entry * 0.0051
    stop_distance = max(
        atr_stop_distance,
        minimum_stop_distance,
    )

    stop_loss = round(
        entry + stop_distance,
        decimals,
    )

    # Target mengikuti risk unit aktual, bukan ATR lama,
    # supaya risk/reward tetap konsisten.
    take_profit = [
        round(entry - (stop_distance * multiple), decimals)
        for multiple in (1.0, 1.67, 2.33)
    ]

    risk_per_unit = stop_loss - entry
    reward_per_unit = entry - take_profit[1]
    risk_reward = (
        round(reward_per_unit / risk_per_unit, 2)
        if risk_per_unit > 0
        else 0.0
    )

    risk = (
        "LOW"
        if score.confidence >= 90 and risk_reward >= 1.5
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