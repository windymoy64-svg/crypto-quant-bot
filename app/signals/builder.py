from __future__ import annotations

from app.core.models import Candle, ScoreResult, TradingSignal
from app.indicators.technical import atr


def build_signal(symbol: str, candles: list[Candle], score: ScoreResult) -> TradingSignal:
    entry = candles[-1].close
    current_atr = atr(candles)
    stop_loss = round(entry - (current_atr * 1.5), 2)
    take_profit = [round(entry + (current_atr * multiple), 2) for multiple in (1.5, 2.5, 3.5)]
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
        entry=round(entry, 2),
        stop_loss=stop_loss,
        take_profit=take_profit,
        risk_reward=risk_reward,
        risk=risk,
        strategy="Weighted Rule Engine",
        meta=meta,
    )
    
