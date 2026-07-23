"""Chart Reader Agent — main orchestrator.

This is the "brain" that combines all techniques adaptively based on market
conditions. It reads candles from multiple timeframes, runs all available
detectors and strategies, then produces a unified ChartReading.

Key design:
- Pure Python, no external AI/LLM dependency
- Deterministic: same input always produces same output
- Adaptive: selects and weights techniques based on detected market regime
- Integrates existing bot modules (ACR+, Liquidity S/R MTF, scoring engine)
- Adds new detection layers (40+ candle patterns, order blocks, BOS/CHoCH)
- Output is advisory context, NOT a trade decision

Usage:
    from app.chart_agent.agent import ChartReaderAgent

    agent = ChartReaderAgent()
    reading = agent.read(
        symbol="BTC/USDT",
        htf_candles=candles_4h,
        mtf_candles=candles_1h,
        ltf_candles=candles_5m,
    )
    print(reading.to_dict())
"""

from __future__ import annotations

from typing import Any

from app.core.models import Candle
from app.chart_agent.models import (
    BiasDirection,
    BreakerBlock,
    CandlePatternDetection,
    ChartReading,
    KeyLevel,
    OrderBlock,
    StructureBreak,
    TechniqueSignal,
)
from app.chart_agent.candle_patterns import detect_all_patterns
from app.chart_agent.structure_reader import (
    detect_breaker_blocks,
    detect_order_blocks,
    detect_structure_breaks,
)
from app.chart_agent.confluence_engine import (
    calculate_confluence,
    get_regime_weight,
    meets_confluence_threshold,
)
from app.chart_agent.level_placement import atr_from_candles, select_entry_invalidation


# ---------------------------------------------------------------------------
# Internal technique adapters
# ---------------------------------------------------------------------------


def _run_regime_analysis(candles: list[Candle]) -> TechniqueSignal:
    """Run market regime detection using existing module."""
    try:
        from app.features.builder import build_features
        from app.market.regime import MarketRegimeEngine

        features = build_features(candles)
        engine = MarketRegimeEngine()
        regime = engine.analyze(features)

        if regime.regime in ("TRENDING_BULLISH",):
            bias: BiasDirection = "BULLISH"
        elif regime.regime in ("TRENDING_BEARISH",):
            bias = "BEARISH"
        else:
            bias = "NEUTRAL"

        return TechniqueSignal(
            technique="regime_indicators",
            bias=bias,
            confidence=regime.confidence,
            weight=1.0,
            reasons=[
                f"regime={regime.regime}",
                f"trend_strength={regime.trend_strength}",
                f"volatility={regime.volatility_state}",
                f"volume={regime.volume_state}",
            ],
            meta=regime.to_dict(),
        )
    except Exception:
        return TechniqueSignal(
            technique="regime_indicators",
            bias="NEUTRAL",
            confidence=0.0,
            weight=0.5,
            reasons=["regime_analysis_unavailable"],
        )


def _run_candle_pattern_analysis(
    candles: list[Candle],
) -> tuple[list[CandlePatternDetection], TechniqueSignal]:
    """Detect candle patterns and produce a technique signal."""
    patterns = detect_all_patterns(candles)
    if not patterns:
        signal = TechniqueSignal(
            technique="candle_patterns",
            bias="NEUTRAL",
            confidence=0.0,
            weight=0.8,
            reasons=["no_patterns_detected"],
        )
        return [], signal

    # Aggregate bias from patterns
    bull_score = sum(p.reliability for p in patterns if p.direction == "BULLISH")
    bear_score = sum(p.reliability for p in patterns if p.direction == "BEARISH")
    total = bull_score + bear_score
    if total <= 0:
        bias: BiasDirection = "NEUTRAL"
        confidence = 0.0
    elif bull_score > bear_score:
        bias = "BULLISH"
        confidence = min(100.0, (bull_score / total) * 100)
    elif bear_score > bull_score:
        bias = "BEARISH"
        confidence = min(100.0, (bear_score / total) * 100)
    else:
        bias = "NEUTRAL"
        confidence = 30.0

    # Pick strongest pattern
    strongest = max(patterns, key=lambda p: p.reliability)
    reasons = [
        f"strongest={strongest.name}({strongest.direction})",
        f"bullish_patterns={sum(1 for p in patterns if p.direction == 'BULLISH')}",
        f"bearish_patterns={sum(1 for p in patterns if p.direction == 'BEARISH')}",
    ]

    signal = TechniqueSignal(
        technique="candle_patterns",
        bias=bias,
        confidence=round(confidence, 1),
        weight=0.8,
        reasons=reasons,
        meta={"pattern_count": len(patterns), "strongest": strongest.name},
    )
    return patterns, signal


def _run_structure_analysis(
    candles: list[Candle],
) -> tuple[list[StructureBreak], list[OrderBlock], TechniqueSignal]:
    """Run BOS/CHoCH and order block detection."""
    breaks = detect_structure_breaks(candles)
    obs = detect_order_blocks(candles)

    if not breaks:
        signal = TechniqueSignal(
            technique="structure",
            bias="NEUTRAL",
            confidence=0.0,
            weight=1.0,
            reasons=["no_structure_breaks"],
        )
        return [], obs, signal

    latest = breaks[-1]
    bias: BiasDirection = "BULLISH" if latest.direction == "BULLISH" else "BEARISH"
    confidence = 75.0 if latest.break_type == "CHoCH" else 60.0

    recent_bos = sum(1 for b in breaks if b.break_type == "BOS")
    recent_choch = sum(1 for b in breaks if b.break_type == "CHoCH")
    reasons = [
        f"latest={latest.break_type}_{latest.direction}",
        f"bos_count={recent_bos}",
        f"choch_count={recent_choch}",
    ]

    fresh_obs = [ob for ob in obs if not ob.mitigated]
    if fresh_obs:
        reasons.append(f"fresh_order_blocks={len(fresh_obs)}")
        confidence = min(100.0, confidence + len(fresh_obs) * 5)

    signal = TechniqueSignal(
        technique="structure",
        bias=bias,
        confidence=round(confidence, 1),
        weight=1.2,
        reasons=reasons,
        meta={"latest_break": latest.break_type, "ob_count": len(obs)},
    )
    return breaks, obs, signal



def _run_acr_analysis(candles: list[Candle]) -> TechniqueSignal:
    """Run full ACR+ analysis: pattern, FVG, CISD, MSS, opposing, equilibrium."""
    try:
        from app.indicators.acr import (
            latest_acr_pattern,
            fair_value_gaps,
            latest_unfilled_fvg,
            cisd_levels,
            latest_cisd,
            mss_events,
            opposing_candles,
            latest_opposing,
            latest_equilibrium_range,
            acr_swings,
        )

        pattern = latest_acr_pattern(candles)
        fvgs = fair_value_gaps(candles)
        unfilled_bull = latest_unfilled_fvg(fvgs, "BULLISH")
        unfilled_bear = latest_unfilled_fvg(fvgs, "BEARISH")

        # CISD analysis
        cisds = cisd_levels(candles)
        bull_cisd = latest_cisd(cisds, "BULLISH")
        bear_cisd = latest_cisd(cisds, "BEARISH")

        # MSS analysis
        swings = acr_swings(candles)
        mss_list = mss_events(candles, swings)

        # Opposing candle levels
        opps = opposing_candles(candles)
        bull_opposing = latest_opposing(opps, "BULLISH")
        bear_opposing = latest_opposing(opps, "BEARISH")

        # Equilibrium (premium/discount)
        eq_range = latest_equilibrium_range(candles)

        reasons: list[str] = []
        confidence = 0.0
        meta: dict[str, Any] = {}

        # --- ACR pattern ---
        if pattern is not None and pattern.is_actionable:
            bias: BiasDirection = "BULLISH" if pattern.direction == "BULLISH" else "BEARISH"
            confidence = 70.0 if pattern.stage == "confirmed" else 60.0
            reasons.append(f"acr_pattern={pattern.direction}_{pattern.stage}")
            meta["acr_pattern"] = pattern.to_dict()
        else:
            bias = "NEUTRAL"
            reasons.append("no_actionable_acr_pattern")

        # --- FVG ---
        if unfilled_bull and not unfilled_bear:
            if bias == "NEUTRAL":
                bias = "BULLISH"
                confidence = 40.0
            elif bias == "BULLISH":
                confidence = min(100.0, confidence + 15)
            reasons.append("unfilled_bullish_fvg")
        elif unfilled_bear and not unfilled_bull:
            if bias == "NEUTRAL":
                bias = "BEARISH"
                confidence = 40.0
            elif bias == "BEARISH":
                confidence = min(100.0, confidence + 15)
            reasons.append("unfilled_bearish_fvg")

        # --- CISD ---
        if bull_cisd and not bear_cisd:
            if bias == "BULLISH":
                confidence = min(100.0, confidence + 10)
            reasons.append(f"bullish_cisd_at_{bull_cisd.price:.2f}")
        elif bear_cisd and not bull_cisd:
            if bias == "BEARISH":
                confidence = min(100.0, confidence + 10)
            reasons.append(f"bearish_cisd_at_{bear_cisd.price:.2f}")
        elif bull_cisd and bear_cisd:
            reasons.append("cisd_conflict")

        # --- MSS ---
        if mss_list:
            latest_mss = mss_list[-1]
            if latest_mss.direction == "BULLISH" and bias == "BULLISH":
                confidence = min(100.0, confidence + 8)
            elif latest_mss.direction == "BEARISH" and bias == "BEARISH":
                confidence = min(100.0, confidence + 8)
            reasons.append(f"mss_{latest_mss.direction.lower()}")

        # --- Opposing candle ---
        if bull_opposing:
            reasons.append(f"opposing_bull_level={bull_opposing.price:.2f}")
        if bear_opposing:
            reasons.append(f"opposing_bear_level={bear_opposing.price:.2f}")

        # --- Equilibrium / Premium-Discount ---
        if eq_range and candles:
            current_price = candles[-1].close
            if eq_range.is_discount(current_price):
                if bias in ("BULLISH", "NEUTRAL"):
                    confidence = min(100.0, confidence + 10)
                    if bias == "NEUTRAL":
                        bias = "BULLISH"
                        confidence = 45.0
                reasons.append("price_in_discount_zone")
            elif eq_range.is_premium(current_price):
                if bias in ("BEARISH", "NEUTRAL"):
                    confidence = min(100.0, confidence + 10)
                    if bias == "NEUTRAL":
                        bias = "BEARISH"
                        confidence = 45.0
                reasons.append("price_in_premium_zone")
            meta["equilibrium"] = eq_range.to_dict()

        meta["fvg_count"] = len(fvgs)
        meta["cisd_count"] = len(cisds)
        meta["mss_count"] = len(mss_list)
        meta["opposing_count"] = len(opps)
        meta["has_pattern"] = pattern is not None

        return TechniqueSignal(
            technique="acr_plus",
            bias=bias,
            confidence=round(min(100.0, confidence), 1),
            weight=1.2,
            reasons=reasons,
            meta=meta,
        )
    except Exception:
        return TechniqueSignal(
            technique="acr_plus",
            bias="NEUTRAL",
            confidence=0.0,
            weight=0.5,
            reasons=["acr_analysis_unavailable"],
        )



def _run_liquidity_sr_analysis(
    htf_candles: list[Candle],
    mtf_candles: list[Candle],
    ltf_candles: list[Candle],
) -> TechniqueSignal:
    """Run Liquidity S/R MTF strategy using existing module."""
    try:
        from app.strategies.liquidity_sr_mtf import MTFContext, evaluate

        ctx = MTFContext(big=htf_candles, mid=mtf_candles, small=ltf_candles)
        decision = evaluate(ctx)

        if decision.action == "BUY":
            bias: BiasDirection = "BULLISH"
            confidence = 80.0
        elif decision.action == "SELL":
            bias = "BEARISH"
            confidence = 80.0
        else:
            bias = "NEUTRAL"
            confidence = 20.0

        return TechniqueSignal(
            technique="liquidity_sr_mtf",
            bias=bias,
            confidence=confidence,
            weight=1.3,
            reasons=decision.reasons,
            meta={
                "action": decision.action,
                "aligned": decision.mtf_alignment.aligned,
                "entry": decision.entry,
                "stop_loss": decision.stop_loss,
            },
        )
    except Exception:
        return TechniqueSignal(
            technique="liquidity_sr_mtf",
            bias="NEUTRAL",
            confidence=0.0,
            weight=0.5,
            reasons=["liquidity_sr_analysis_unavailable"],
        )


def _run_liquidity_pools_analysis(candles: list[Candle]) -> TechniqueSignal:
    """Direct liquidity pool + sweep analysis (independent from strategy).

    This runs the raw liquidity primitives so the agent always sees pool/sweep
    data even when the full liquidity_sr_mtf strategy returns HOLD.
    """
    try:
        from app.indicators.liquidity_structure import (
            swing_points,
            liquidity_pools,
            sweep_events,
            sr_zones,
        )

        swings = swing_points(candles)
        pools = liquidity_pools(candles, swings)
        sweeps = sweep_events(candles, pools)
        zones = sr_zones(candles, swings)

        fresh_buy_pools = [p for p in pools if p.side == "BUY_SIDE" and p.fresh]
        fresh_sell_pools = [p for p in pools if p.side == "SELL_SIDE" and p.fresh]
        confirmed_sweeps = [s for s in sweeps if s.confirmed]

        reasons: list[str] = []
        confidence = 0.0

        # Fresh pools indicate where liquidity sits (unswept)
        reasons.append(f"fresh_buy_pools={len(fresh_buy_pools)}")
        reasons.append(f"fresh_sell_pools={len(fresh_sell_pools)}")

        # Confirmed sweep = liquidity grab = potential reversal
        if confirmed_sweeps:
            latest_sweep = confirmed_sweeps[-1]
            if latest_sweep.pool_side == "SELL_SIDE":
                # Swept sell-side (below lows) -> bullish reversal expected
                bias: BiasDirection = "BULLISH"
                confidence = 65.0
                reasons.append("confirmed_sell_side_sweep_bullish")
            else:
                # Swept buy-side (above highs) -> bearish reversal expected
                bias = "BEARISH"
                confidence = 65.0
                reasons.append("confirmed_buy_side_sweep_bearish")
        elif fresh_sell_pools and not fresh_buy_pools:
            # Only sell-side liquidity fresh -> price may hunt it (bearish short-term)
            bias = "NEUTRAL"
            confidence = 30.0
            reasons.append("sell_side_liquidity_target")
        elif fresh_buy_pools and not fresh_sell_pools:
            bias = "NEUTRAL"
            confidence = 30.0
            reasons.append("buy_side_liquidity_target")
        else:
            bias = "NEUTRAL"
            confidence = 20.0
            reasons.append("balanced_liquidity")

        # S/R zone context
        active_support = [z for z in zones if z.kind == "SUPPORT" and not z.mitigated]
        active_resist = [z for z in zones if z.kind == "RESISTANCE" and not z.mitigated]
        if active_support:
            reasons.append(f"active_support_zones={len(active_support)}")
        if active_resist:
            reasons.append(f"active_resistance_zones={len(active_resist)}")

        return TechniqueSignal(
            technique="liquidity_pools",
            bias=bias,
            confidence=round(confidence, 1),
            weight=1.1,
            reasons=reasons,
            meta={
                "total_pools": len(pools),
                "fresh_buy": len(fresh_buy_pools),
                "fresh_sell": len(fresh_sell_pools),
                "confirmed_sweeps": len(confirmed_sweeps),
                "active_support": len(active_support),
                "active_resistance": len(active_resist),
            },
        )
    except Exception:
        return TechniqueSignal(
            technique="liquidity_pools",
            bias="NEUTRAL",
            confidence=0.0,
            weight=0.5,
            reasons=["liquidity_pools_analysis_unavailable"],
        )




def _run_momentum_analysis(candles: list[Candle]) -> TechniqueSignal:
    """Analyze momentum via EMA stack, RSI, MACD from existing features."""
    try:
        from app.features.builder import build_features

        features = build_features(candles)
        bull_points = 0
        bear_points = 0
        reasons: list[str] = []

        if features.get("ema_stack_bullish"):
            bull_points += 2
            reasons.append("ema_stack_bullish")
        elif features.get("ema_stack_bearish"):
            bear_points += 2
            reasons.append("ema_stack_bearish")

        if features.get("macd_bullish"):
            bull_points += 1
            reasons.append("macd_bullish")
        elif features.get("macd_bearish"):
            bear_points += 1
            reasons.append("macd_bearish")

        rsi = float(features.get("rsi", 50.0))
        if rsi >= 55:
            bull_points += 1
            reasons.append(f"rsi={rsi:.0f}_bullish")
        elif rsi <= 45:
            bear_points += 1
            reasons.append(f"rsi={rsi:.0f}_bearish")

        if features.get("momentum_5_positive") and features.get("momentum_10_positive"):
            bull_points += 1
            reasons.append("momentum_positive")
        elif features.get("momentum_5_negative") and features.get("momentum_10_negative"):
            bear_points += 1
            reasons.append("momentum_negative")

        total = bull_points + bear_points
        if total == 0:
            return TechniqueSignal(
                technique="momentum", bias="NEUTRAL",
                confidence=30.0, weight=1.0, reasons=["no_clear_momentum"],
            )

        if bull_points > bear_points:
            bias: BiasDirection = "BULLISH"
            confidence = min(100.0, (bull_points / max(total, 1)) * 100)
        elif bear_points > bull_points:
            bias = "BEARISH"
            confidence = min(100.0, (bear_points / max(total, 1)) * 100)
        else:
            bias = "NEUTRAL"
            confidence = 30.0

        return TechniqueSignal(
            technique="momentum", bias=bias,
            confidence=round(confidence, 1), weight=1.0, reasons=reasons,
        )
    except Exception:
        return TechniqueSignal(
            technique="momentum", bias="NEUTRAL",
            confidence=0.0, weight=0.5, reasons=["momentum_unavailable"],
        )



# ---------------------------------------------------------------------------
# Narrative generator
# ---------------------------------------------------------------------------


def _build_narrative(
    bias: BiasDirection,
    confluence_score: float,
    regime: str,
    signals: list[TechniqueSignal],
    patterns: list[CandlePatternDetection],
    breaks: list[StructureBreak],
) -> str:
    """Generate human-readable narrative from analysis results."""
    parts: list[str] = []

    # Market context
    regime_label = regime.replace("_", " ").title()
    parts.append(f"Market regime: {regime_label}.")

    # Bias
    if bias == "NEUTRAL":
        parts.append("Tidak ada bias arah yang jelas.")
    else:
        parts.append(f"Bias dominan: {bias} (confluence {confluence_score:.0f}%).")

    # Key technique insights
    for sig in signals:
        if sig.confidence >= 60:
            parts.append(f"{sig.technique}: {sig.bias} ({sig.confidence:.0f}%).")

    # Patterns
    if patterns:
        strong = [p for p in patterns if p.strength == "STRONG"]
        if strong:
            names = ", ".join(p.name for p in strong[:3])
            parts.append(f"Pattern kuat: {names}.")

    # Structure
    if breaks:
        latest = breaks[-1]
        parts.append(f"Structure: {latest.break_type} {latest.direction}.")

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Key level extraction
# ---------------------------------------------------------------------------


def _extract_key_levels(
    candles: list[Candle],
    obs: list[OrderBlock],
) -> list[KeyLevel]:
    """Extract important price levels from analysis results."""
    levels: list[KeyLevel] = []

    # From order blocks
    for ob in obs:
        if not ob.mitigated:
            kind = "support" if ob.direction == "BULLISH" else "resistance"
            levels.append(KeyLevel(
                price=ob.midpoint,
                kind=kind,
                strength="STRONG",
                source="order_block",
                fresh=not ob.tested,
            ))

    # Recent swing high/low as key levels
    if len(candles) >= 5:
        recent_high = max(c.high for c in candles[-20:])
        recent_low = min(c.low for c in candles[-20:])
        levels.append(KeyLevel(
            price=recent_high,
            kind="resistance",
            strength="MODERATE",
            source="swing_high",
            fresh=True,
        ))
        levels.append(KeyLevel(
            price=recent_low,
            kind="support",
            strength="MODERATE",
            source="swing_low",
            fresh=True,
        ))

    return levels


# ---------------------------------------------------------------------------
# Trend helper
# ---------------------------------------------------------------------------


def _determine_trend(candles: list[Candle]) -> str:
    """Quick trend determination from candle structure."""
    if len(candles) < 10:
        return "SIDE"
    try:
        from app.indicators.liquidity_structure import swing_points, structure_state
        swings = swing_points(candles)
        state = structure_state(swings)
        return state.trend
    except Exception:
        # Fallback: simple EMA comparison
        closes = [c.close for c in candles]
        if len(closes) >= 20:
            ema20 = sum(closes[-20:]) / 20
            ema50 = sum(closes[-min(50, len(closes)):]) / min(50, len(closes))
            if closes[-1] > ema20 > ema50:
                return "UP"
            elif closes[-1] < ema20 < ema50:
                return "DOWN"
        return "SIDE"



# ---------------------------------------------------------------------------
# Main Agent class
# ---------------------------------------------------------------------------


class ChartReaderAgent:
    """Pure Python chart reading agent that combines all techniques.

    Adaptively selects and weights techniques based on detected market regime.
    Output is a structured ChartReading — advisory context, not a trade decision.
    """

    def read(
        self,
        symbol: str,
        htf_candles: list[Candle],
        mtf_candles: list[Candle],
        ltf_candles: list[Candle],
    ) -> ChartReading:
        """Read the chart across all timeframes and produce analysis.

        Args:
            symbol: Trading pair (e.g. "BTC/USDT").
            htf_candles: Higher timeframe candles (e.g. 4h).
            mtf_candles: Medium timeframe candles (e.g. 1h).
            ltf_candles: Lower timeframe candles (e.g. 5m/15m).

        Returns:
            ChartReading with complete analysis.
        """
        timestamp = ltf_candles[-1].timestamp if ltf_candles else ""
        techniques_used: list[str] = []
        all_signals: list[TechniqueSignal] = []

        # 1. Market regime (from HTF)
        regime_signal = _run_regime_analysis(htf_candles)
        all_signals.append(regime_signal)
        techniques_used.append("regime_indicators")
        regime_name = regime_signal.meta.get("regime", "MIXED") if regime_signal.meta else "MIXED"

        # 2. Momentum analysis (from MTF)
        momentum_signal = _run_momentum_analysis(mtf_candles)
        all_signals.append(momentum_signal)
        techniques_used.append("momentum")

        # 3. Structure analysis (BOS/CHoCH/OB from MTF)
        breaks, obs, structure_signal = _run_structure_analysis(mtf_candles)
        all_signals.append(structure_signal)
        techniques_used.append("structure")

        # 4. ACR+ analysis (from LTF)
        acr_signal = _run_acr_analysis(ltf_candles)
        all_signals.append(acr_signal)
        techniques_used.append("acr_plus")

        # 5. Candle patterns (from LTF — most recent)
        patterns, pattern_signal = _run_candle_pattern_analysis(ltf_candles)
        all_signals.append(pattern_signal)
        techniques_used.append("candle_patterns")

        # 6. Liquidity S/R MTF (full multi-TF strategy)
        liq_signal = _run_liquidity_sr_analysis(htf_candles, mtf_candles, ltf_candles)
        all_signals.append(liq_signal)
        techniques_used.append("liquidity_sr_mtf")

        # 7. Direct liquidity pools + sweep analysis (from MTF)
        pools_signal = _run_liquidity_pools_analysis(mtf_candles)
        all_signals.append(pools_signal)
        techniques_used.append("liquidity_pools")

        # 8. Calculate confluence
        bias, bias_confidence, confluence_score = calculate_confluence(
            all_signals, regime_name
        )

        # 8. Determine trends per TF
        htf_trend = _determine_trend(htf_candles)
        mtf_trend = _determine_trend(mtf_candles)
        ltf_trend = _determine_trend(ltf_candles)
        trends_aligned = (
            htf_trend == mtf_trend and htf_trend != "SIDE"
        )

        # 9. Extract key levels
        key_levels = _extract_key_levels(ltf_candles, obs)

        # 10. Breaker blocks
        breaker_blocks = detect_breaker_blocks(obs, mtf_candles)

        # 11. Build narrative
        narrative = _build_narrative(
            bias, confluence_score, regime_name, all_signals, patterns, breaks
        )

        # 12. Structure + ATR entry zone / invalidation (not nearest-noise SL)
        entry_zone: tuple[float, float] | None = None
        invalidation: float | None = None
        level_meta: dict[str, Any] = {}
        if ltf_candles:
            current_price = float(ltf_candles[-1].close)
            atr_value = atr_from_candles(ltf_candles, current_price)
            entry_zone, invalidation, _source, level_meta = select_entry_invalidation(
                bias=bias,
                current_price=current_price,
                atr_value=atr_value,
                liq_signal=liq_signal,
                obs=obs,
                key_levels=key_levels,
                htf_candles=htf_candles,
                mtf_candles=mtf_candles,
                ltf_candles=ltf_candles,
            )

        # Collect reasons
        reasons: list[str] = []
        for sig in all_signals:
            if sig.confidence >= 50:
                reasons.append(f"{sig.technique}:{sig.bias}")

        if entry_zone is not None and level_meta:
            reasons.append(f"entry_zone_dist={level_meta.get('zone_dist_pct', 0):.2f}%")
            reasons.append(f"sl_atr={level_meta.get('sl_atr', 0):.2f}")
            reasons.append(f"sl_pct={level_meta.get('sl_pct', 0):.2f}%")
            if level_meta.get("source"):
                reasons.append(f"level_source={level_meta['source']}")
        elif level_meta.get("reject"):
            reasons.append(f"level_reject={level_meta['reject']}")

        return ChartReading(
            symbol=symbol,
            timestamp=timestamp,
            bias=bias,
            bias_confidence=bias_confidence,
            confluence_score=confluence_score,
            regime=regime_name,
            regime_confidence=regime_signal.confidence,
            htf_trend=htf_trend,
            mtf_trend=mtf_trend,
            ltf_trend=ltf_trend,
            trends_aligned=trends_aligned,
            candle_patterns=patterns,
            structure_breaks=breaks,
            order_blocks=obs,
            key_levels=key_levels,
            technique_signals=all_signals,
            narrative=narrative,
            reasons=reasons,
            suggested_bias=bias,
            entry_zone=entry_zone,
            invalidation_level=invalidation,
            techniques_used=techniques_used,
            meta={
                "meets_threshold": meets_confluence_threshold(
                    confluence_score, regime_name
                ),
                "level_placement": level_meta,
            },
        )

