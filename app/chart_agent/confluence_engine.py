"""Confluence engine — combines all technique signals into a single score.

The engine weights each technique based on the current market regime and
calculates how many signals agree (confluence). Higher confluence = higher
probability setup.

Regime-adaptive weighting:
- TRENDING: trend-following techniques weighted higher (structure, MTF, momentum)
- RANGING: mean-reversion techniques weighted higher (S/R, patterns, OB)
- HIGH_VOLATILITY: only strong confluence passes (raise threshold)
"""

from __future__ import annotations

from typing import Any, Literal

from app.chart_agent.models import BiasDirection, TechniqueSignal


# ---------------------------------------------------------------------------
# Regime-based weight profiles
# ---------------------------------------------------------------------------

REGIME_WEIGHTS: dict[str, dict[str, float]] = {
    "TRENDING_BULLISH": {
        "structure": 1.5,
        "acr_plus": 1.3,
        "liquidity_sr_mtf": 1.2,
        "candle_patterns": 0.8,
        "regime_indicators": 1.0,
        "order_blocks": 1.0,
        "fvg": 1.1,
        "momentum": 1.4,
    },
    "TRENDING_BEARISH": {
        "structure": 1.5,
        "acr_plus": 1.3,
        "liquidity_sr_mtf": 1.2,
        "candle_patterns": 0.8,
        "regime_indicators": 1.0,
        "order_blocks": 1.0,
        "fvg": 1.1,
        "momentum": 1.4,
    },
    "RANGING": {
        "structure": 0.8,
        "acr_plus": 1.0,
        "liquidity_sr_mtf": 1.4,
        "candle_patterns": 1.3,
        "regime_indicators": 1.0,
        "order_blocks": 1.5,
        "fvg": 1.2,
        "momentum": 0.6,
    },
    "HIGH_VOLATILITY": {
        "structure": 1.0,
        "acr_plus": 1.2,
        "liquidity_sr_mtf": 1.0,
        "candle_patterns": 0.7,
        "regime_indicators": 1.3,
        "order_blocks": 0.9,
        "fvg": 0.8,
        "momentum": 1.1,
    },
    "MIXED": {
        "structure": 1.0,
        "acr_plus": 1.0,
        "liquidity_sr_mtf": 1.0,
        "candle_patterns": 1.0,
        "regime_indicators": 1.0,
        "order_blocks": 1.0,
        "fvg": 1.0,
        "momentum": 1.0,
    },
}

# Minimum confluence thresholds per regime
CONFLUENCE_THRESHOLDS: dict[str, float] = {
    "TRENDING_BULLISH": 55.0,
    "TRENDING_BEARISH": 55.0,
    "RANGING": 60.0,
    "HIGH_VOLATILITY": 70.0,
    "MIXED": 60.0,
}


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


def get_regime_weight(regime: str, technique: str) -> float:
    """Get the weight multiplier for a technique in the given regime."""
    profile = REGIME_WEIGHTS.get(regime, REGIME_WEIGHTS["MIXED"])
    return profile.get(technique, 1.0)


def calculate_confluence(
    signals: list[TechniqueSignal],
    regime: str,
) -> tuple[BiasDirection, float, float]:
    """Calculate overall bias and confluence score from technique signals.

    Returns:
        (bias, bias_confidence, confluence_score)
        - bias: BULLISH, BEARISH, or NEUTRAL
        - bias_confidence: 0-100, weighted average confidence
        - confluence_score: 0-100, how much signals agree
    """
    if not signals:
        return "NEUTRAL", 0.0, 0.0

    bullish_weight = 0.0
    bearish_weight = 0.0
    neutral_weight = 0.0
    total_weight = 0.0

    for sig in signals:
        regime_multiplier = get_regime_weight(regime, sig.technique)
        effective_weight = sig.weight * regime_multiplier
        weighted_confidence = sig.confidence * effective_weight

        if sig.bias == "BULLISH":
            bullish_weight += weighted_confidence
        elif sig.bias == "BEARISH":
            bearish_weight += weighted_confidence
        else:
            neutral_weight += weighted_confidence

        total_weight += effective_weight * 100  # normalize base

    if total_weight <= 0:
        return "NEUTRAL", 0.0, 0.0

    # Determine bias
    if bullish_weight > bearish_weight and bullish_weight > neutral_weight:
        bias: BiasDirection = "BULLISH"
        dominant_weight = bullish_weight
    elif bearish_weight > bullish_weight and bearish_weight > neutral_weight:
        bias = "BEARISH"
        dominant_weight = bearish_weight
    else:
        bias = "NEUTRAL"
        dominant_weight = neutral_weight

    # Bias confidence: how strong the dominant signal is (0-100)
    bias_confidence = min(100.0, (dominant_weight / total_weight) * 200)

    # Confluence score: % of signals agreeing with the dominant bias
    agreeing = sum(
        1 for s in signals if s.bias == bias
    )
    confluence_score = (agreeing / len(signals)) * 100 if signals else 0.0

    return bias, round(bias_confidence, 1), round(confluence_score, 1)


def meets_confluence_threshold(
    confluence_score: float,
    regime: str,
) -> bool:
    """Check if confluence score meets the minimum threshold for the regime."""
    threshold = CONFLUENCE_THRESHOLDS.get(regime, 60.0)
    return confluence_score >= threshold


def rank_techniques_by_relevance(
    regime: str,
) -> list[tuple[str, float]]:
    """Return techniques sorted by relevance for the current regime."""
    profile = REGIME_WEIGHTS.get(regime, REGIME_WEIGHTS["MIXED"])
    return sorted(profile.items(), key=lambda x: x[1], reverse=True)
