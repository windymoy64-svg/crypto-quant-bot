"""Confluence engine with family score caps."""

from __future__ import annotations

from app.chart_agent.models import BiasDirection, TechniqueSignal

REGIME_WEIGHTS = {
    "TRENDING_BULLISH": {"structure": 1.5, "acr_plus": 1.3, "liquidity_sr_mtf": 1.2, "candle_patterns": 0.8, "regime_indicators": 1.0, "order_blocks": 1.0, "fvg": 1.1, "momentum": 1.4, "liquidity_pools": 1.1},
    "TRENDING_BEARISH": {"structure": 1.5, "acr_plus": 1.3, "liquidity_sr_mtf": 1.2, "candle_patterns": 0.8, "regime_indicators": 1.0, "order_blocks": 1.0, "fvg": 1.1, "momentum": 1.4, "liquidity_pools": 1.1},
    "RANGING": {"structure": 0.8, "acr_plus": 1.0, "liquidity_sr_mtf": 1.4, "candle_patterns": 1.3, "regime_indicators": 1.0, "order_blocks": 1.5, "fvg": 1.2, "momentum": 0.6, "liquidity_pools": 1.3},
    "HIGH_VOLATILITY": {"structure": 1.0, "acr_plus": 1.2, "liquidity_sr_mtf": 1.0, "candle_patterns": 0.7, "regime_indicators": 1.3, "order_blocks": 0.9, "fvg": 0.8, "momentum": 1.1, "liquidity_pools": 1.0},
    "MIXED": {"structure": 1.0, "acr_plus": 1.0, "liquidity_sr_mtf": 1.0, "candle_patterns": 1.0, "regime_indicators": 1.0, "order_blocks": 1.0, "fvg": 1.0, "momentum": 1.0, "liquidity_pools": 1.0},
}
CONFLUENCE_THRESHOLDS = {"TRENDING_BULLISH": 55.0, "TRENDING_BEARISH": 55.0, "RANGING": 60.0, "HIGH_VOLATILITY": 70.0, "MIXED": 60.0}
TECHNIQUE_FAMILIES = {"regime_indicators": "trend", "momentum": "momentum", "structure": "structure", "acr_plus": "structure", "order_blocks": "structure", "fvg": "structure", "liquidity_sr_mtf": "liquidity", "liquidity_pools": "liquidity", "candle_patterns": "patterns"}
FAMILY_CAPS = {"trend": 25.0, "momentum": 15.0, "structure": 25.0, "liquidity": 20.0, "patterns": 10.0, "volume": 5.0, "other": 10.0}

def get_regime_weight(regime: str, technique: str) -> float:
    return REGIME_WEIGHTS.get(regime, REGIME_WEIGHTS["MIXED"]).get(technique, 1.0)

def calculate_confluence(signals: list[TechniqueSignal], regime: str) -> tuple[BiasDirection, float, float]:
    if not signals:
        return "NEUTRAL", 0.0, 0.0
    eligible = [s for s in signals if getattr(s, "analysis_status", "OK") == "OK"]
    if not eligible:
        return "NEUTRAL", 0.0, 0.0
    family_bullish, family_bearish, family_neutral, family_total = {}, {}, {}, {}
    for sig in eligible:
        family = TECHNIQUE_FAMILIES.get(sig.technique, "other")
        eff = sig.weight * get_regime_weight(regime, sig.technique)
        wc = sig.confidence * eff
        if sig.bias == "BULLISH":
            family_bullish[family] = family_bullish.get(family, 0.0) + wc
        elif sig.bias == "BEARISH":
            family_bearish[family] = family_bearish.get(family, 0.0) + wc
        else:
            family_neutral[family] = family_neutral.get(family, 0.0) + wc
        family_total[family] = family_total.get(family, 0.0) + eff * 100.0
    bullish = bearish = neutral = total = 0.0
    for family in set(family_bullish)|set(family_bearish)|set(family_neutral):
        cap = FAMILY_CAPS.get(family, 10.0) * 100.0
        bullish += min(family_bullish.get(family, 0.0), cap)
        bearish += min(family_bearish.get(family, 0.0), cap)
        neutral += min(family_neutral.get(family, 0.0), cap)
        total += min(family_total.get(family, 0.0), cap)
    if total <= 0:
        return "NEUTRAL", 0.0, 0.0
    if bullish > bearish and bullish > neutral:
        bias, dominant = "BULLISH", bullish
    elif bearish > bullish and bearish > neutral:
        bias, dominant = "BEARISH", bearish
    else:
        bias, dominant = "NEUTRAL", neutral
    bias_confidence = min(100.0, (dominant / total) * 200.0)
    agreeing = sum(1 for s in eligible if s.bias == bias)
    confluence_score = (agreeing / len(eligible)) * 100.0
    return bias, round(bias_confidence, 1), round(confluence_score, 1)

def meets_confluence_threshold(confluence_score: float, regime: str) -> bool:
    return confluence_score >= CONFLUENCE_THRESHOLDS.get(regime, 60.0)

def rank_techniques_by_relevance(regime: str) -> list[tuple[str, float]]:
    profile = REGIME_WEIGHTS.get(regime, REGIME_WEIGHTS["MIXED"])
    return sorted(profile.items(), key=lambda x: x[1], reverse=True)
