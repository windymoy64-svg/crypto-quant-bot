"""Decision Maker Agent — core decision logic.

Consumes ChartReading + LearningInsight and produces a Decision.
"""

from __future__ import annotations

from typing import Any

from app.chart_agent.models import ChartReading
from app.learning_agent.models import LearningInsight
from app.decision_agent.models import (
    ActionType,
    Decision,
    DecisionConfidence,
    EntryPlan,
    ExitPlan,
)


# ---------------------------------------------------------------------------
# Configuration thresholds
# ---------------------------------------------------------------------------

DEFAULT_MIN_CONFLUENCE = 55.0
DEFAULT_MIN_CONFIDENCE_ENTRY = 70.0
DEFAULT_MIN_RR = 2.0
# Structural SL must clear noise; reject paper-thin invalidation.
MIN_SL_PCT = 0.35
MAX_SL_PCT = 4.5
# Prefer real HTF target when it clears min RR; else fall back to R-multiples.
TP1_R = 2.0
TP2_R = 3.0
TP3_R = 4.0
LEARNING_BOOST_HOT_PATTERN = 8.0
LEARNING_PENALTY_COLD_PATTERN = -12.0
LEARNING_REGIME_PENALTY = -10.0
HOLD_INVALIDATION_THRESHOLD = 40.0
# Structure quality thresholds for dynamic TP1.
# Below these → structure weak → TP1 enabled (lock partial profit early).
# Above these → structure strong → TP1 disabled (let winners run to TP2/TP3).
TP1_STRONG_CONFLUENCE = 50.0
TP1_WEAK_CONFLUENCE = 40.0
TP1_STRONG_REGIMES = ("TRENDING_BULLISH", "TRENDING_BEARISH")


def _select_take_profits(
    reading: ChartReading,
    entry_price: float,
    risk: float,
) -> tuple[float, float | None, float | None]:
    """Pick TP1/2/3: prefer real HTF structure targets, fall back to R-multiples.

    Pro rule: TP must be a place price *should* go (liquidity / swing), not a
    fixed multiple. We still anchor TP1 to 2R (lock partial), but try to snap
    TP2/TP3 to HTF swing/liquidity levels when they clear the corresponding R.
    """
    long_side = reading.bias == "BULLISH"
    sign = 1.0 if long_side else -1.0
    tp1 = entry_price + sign * risk * TP1_R

    # Candidate structural targets from HTF/MTF (swings + key levels).
    structural: list[float] = []
    for level in reading.key_levels:
        if long_side and level.kind == "resistance" and level.price > entry_price:
            structural.append(level.price)
        if (not long_side) and level.kind == "support" and level.price < entry_price:
            structural.append(level.price)

    # Targets must be in trade direction and beyond their R-multiple floor.
    def _snap(floor_r: float, fallback_r: float) -> float | None:
        floor = entry_price + sign * risk * floor_r
        candidates = [p for p in structural if (p > floor if long_side else p < floor)]
        if candidates:
            # Nearest structural target beyond floor = most likely to be reached.
            return min(candidates, key=lambda p: abs(p - entry_price))
        return entry_price + sign * risk * fallback_r

    tp2 = _snap(TP2_R, TP2_R)
    tp3 = _snap(TP3_R, TP3_R)
    return tp1, tp2, tp3


def is_trend_hold_mode(reading: ChartReading, position_side: str) -> bool:
    """True when HTF/MTF trend-following is intact → skip fixed TPs, hold runner.

    Opposite of weak-structure TP1 locking. Used at entry and on HOLD ticks.
    """
    return not should_enable_tp1(reading, position_side)


def should_enable_tp1(reading: ChartReading, position_side: str) -> bool:
    """Decide whether TP1 (partial close) should fire for an open position.

    Professional rule: ``let winners run, cut early when structure shaky``.
    TP1 is a safety exit — only needed when structure is weak. When structure
    is strong (high confluence, trends aligned, trending regime, no counter
    CHoCH), disable TP1 so the full position rides the trailing stop toward
    TP2/TP3 and maximizes the runner.

    Args:
        reading: latest ChartReading for the symbol.
        position_side: ``BUY`` or ``SELL`` — the side of the open position.

    Returns:
        True  → TP1 enabled  (structure weak, lock partial profit).
        False → TP1 disabled (structure strong, let it run).
    """
    # 1. Counter-trend CHoCH = structure damaged → always enable TP1.
    for brk in reading.structure_breaks:
        if position_side == "BUY" and brk.break_type == "CHoCH" and brk.direction == "BEARISH":
            return True
        if position_side == "SELL" and brk.break_type == "CHoCH" and brk.direction == "BULLISH":
            return True

    # 2. Low confluence → weak structure → enable TP1.
    if reading.confluence_score < TP1_WEAK_CONFLUENCE:
        return True

    # 3. Trends not aligned → conflict → enable TP1.
    if not reading.trends_aligned:
        return True

    # 4. Non-trending regime (RANGING / LOW_VOLATILITY / MIXED) → no momentum → enable TP1.
    if reading.regime not in TP1_STRONG_REGIMES:
        return True

    # 5. Strong structure: high confluence + aligned + trending + no counter CHoCH → disable TP1.
    if reading.confluence_score >= TP1_STRONG_CONFLUENCE:
        return False

    # 6. Middle band (40-50 confluence, otherwise strong) → conservative: enable TP1.
    return True


class DecisionMakerAgent:
    """Produces trading decisions from chart data and historical learning.

    Decision flow:
    1. Check if chart has clear bias + sufficient confluence
    2. Apply learning adjustments (hot/cold patterns, regime performance)
    3. Validate risk:reward meets minimum
    4. Produce ENTRY / HOLD / EXIT / SKIP
    """

    def __init__(
        self,
        min_confluence: float = DEFAULT_MIN_CONFLUENCE,
        min_confidence_entry: float = DEFAULT_MIN_CONFIDENCE_ENTRY,
        min_rr: float = DEFAULT_MIN_RR,
    ) -> None:
        self.min_confluence = min_confluence
        self.min_confidence_entry = min_confidence_entry
        self.min_rr = min_rr

    def decide_entry(
        self,
        reading: ChartReading,
        insight: LearningInsight | None = None,
    ) -> Decision:
        """Decide whether to enter a new position."""
        reasons: list[str] = []
        learning_reasons: list[str] = []
        score = reading.bias_confidence

        # Gate 1: directional bias
        if reading.bias == "NEUTRAL":
            return self._skip(reading, ["no_directional_bias"])

        # Gate 2: confluence threshold (calibrated by learning)
        effective_min = self.min_confluence
        if insight and insight.min_confluence_recommended > 0:
            effective_min = max(self.min_confluence, insight.min_confluence_recommended)
            learning_reasons.append(f"min_confluence_calibrated={effective_min:.0f}")

        if reading.confluence_score < effective_min:
            return self._skip(reading, [
                f"confluence_too_low={reading.confluence_score:.0f}<{effective_min:.0f}"
            ])

        # Gate 3: trend alignment
        if not reading.trends_aligned:
            score -= 10
            reasons.append("trends_not_aligned_penalty")

        # Learning adjustments
        boost = 0.0
        if insight:
            boost = self._apply_learning(reading, insight, learning_reasons)
            score += boost

        # Gate 4: final confidence
        if score < self.min_confidence_entry:
            return self._skip(reading, [
                f"confidence_after_adj={score:.0f}<{self.min_confidence_entry:.0f}"
            ] + reasons)

        # Build entry plan
        entry_plan = self._build_entry_plan(reading)
        if entry_plan is None:
            return self._skip(reading, ["cannot_build_entry_plan"] + reasons)

        # Gate 5: risk:reward
        if entry_plan.risk_reward < self.min_rr:
            return self._skip(reading, [
                f"rr_too_low={entry_plan.risk_reward:.1f}<{self.min_rr}"
            ] + reasons)

        # APPROVED
        action: ActionType = "ENTRY_BUY" if reading.bias == "BULLISH" else "ENTRY_SELL"
        side = "BUY" if reading.bias == "BULLISH" else "SELL"
        # Trend-hold at entry: disable fixed TP ladder so paper does not
        # partial/close at TP1 before the first monitor tick.
        hold_mode = is_trend_hold_mode(reading, side)
        tp1_enabled = not hold_mode
        reasons.insert(0, f"bias={reading.bias}")
        reasons.append(f"confluence={reading.confluence_score:.0f}")
        reasons.append(f"regime={reading.regime}")
        if hold_mode:
            reasons.append("trend_hold_mode_skip_fixed_tp")
        else:
            reasons.append("tp1_enabled_at_entry")

        return Decision(
            action=action,
            symbol=reading.symbol,
            confidence=self._confidence_level(score),
            confidence_score=round(min(100.0, score), 1),
            reasons=reasons,
            entry_plan=entry_plan,
            learning_boost=round(boost, 1),
            learning_reasons=learning_reasons,
            regime=reading.regime,
            confluence_score=reading.confluence_score,
            timestamp=reading.timestamp,
            meta={
                "tp1_enabled": tp1_enabled,
                "hold_mode": hold_mode,
                "skip_fixed_tp": hold_mode,
            },
        )

    def decide_hold(
        self,
        reading: ChartReading,
        position_side: str,
        insight: LearningInsight | None = None,
    ) -> Decision:
        """Decide whether to keep holding an open position."""
        reasons: list[str] = []

        # Bias flipped against position
        if position_side == "BUY" and reading.bias == "BEARISH" and reading.bias_confidence >= 65:
            return Decision(
                action="EXIT", symbol=reading.symbol, confidence="HIGH",
                confidence_score=reading.bias_confidence,
                reasons=["bias_flipped_bearish_against_long"],
                exit_plan=ExitPlan(urgency="NEXT_CANDLE", reason="bias_reversal"),
                regime=reading.regime, confluence_score=reading.confluence_score,
                timestamp=reading.timestamp,
            )
        if position_side == "SELL" and reading.bias == "BULLISH" and reading.bias_confidence >= 65:
            return Decision(
                action="EXIT", symbol=reading.symbol, confidence="HIGH",
                confidence_score=reading.bias_confidence,
                reasons=["bias_flipped_bullish_against_short"],
                exit_plan=ExitPlan(urgency="NEXT_CANDLE", reason="bias_reversal"),
                regime=reading.regime, confluence_score=reading.confluence_score,
                timestamp=reading.timestamp,
            )

        # CHoCH against position
        for brk in reading.structure_breaks:
            if position_side == "BUY" and brk.direction == "BEARISH" and brk.break_type == "CHoCH":
                return Decision(
                    action="EXIT", symbol=reading.symbol, confidence="HIGH",
                    confidence_score=80.0, reasons=["choch_bearish_against_long"],
                    exit_plan=ExitPlan(urgency="IMMEDIATE", reason="structure_invalidation"),
                    regime=reading.regime, confluence_score=reading.confluence_score,
                    timestamp=reading.timestamp,
                )
            if position_side == "SELL" and brk.direction == "BULLISH" and brk.break_type == "CHoCH":
                return Decision(
                    action="EXIT", symbol=reading.symbol, confidence="HIGH",
                    confidence_score=80.0, reasons=["choch_bullish_against_short"],
                    exit_plan=ExitPlan(urgency="IMMEDIATE", reason="structure_invalidation"),
                    regime=reading.regime, confluence_score=reading.confluence_score,
                    timestamp=reading.timestamp,
                )

        # Confluence degraded
        if reading.confluence_score < HOLD_INVALIDATION_THRESHOLD:
            return Decision(
                action="EXIT", symbol=reading.symbol, confidence="MEDIUM",
                confidence_score=55.0,
                reasons=[f"confluence_below_threshold={reading.confluence_score:.0f}"],
                exit_plan=ExitPlan(urgency="NEXT_CANDLE", reason="confluence_degraded"),
                regime=reading.regime, confluence_score=reading.confluence_score,
                timestamp=reading.timestamp,
            )

        # All good — HOLD
        reasons.append("structure_intact")
        if reading.trends_aligned:
            reasons.append("trends_aligned")

        # Dynamic TP1: strong structure disables TP1 (let winners run), weak
        # structure enables it (lock partial profit). The paper engine reads
        # ``meta["tp1_enabled"]`` to decide whether the TP1 partial fires.
        tp1_enabled = should_enable_tp1(reading, position_side)
        if tp1_enabled:
            reasons.append("tp1_enabled_weak_structure")
        else:
            reasons.append("tp1_disabled_let_runner")

        return Decision(
            action="HOLD", symbol=reading.symbol, confidence="MEDIUM",
            confidence_score=reading.bias_confidence, reasons=reasons,
            regime=reading.regime, confluence_score=reading.confluence_score,
            timestamp=reading.timestamp,
            meta={
                "tp1_enabled": tp1_enabled,
                "hold_mode": not tp1_enabled,
                "skip_fixed_tp": not tp1_enabled,
            },
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _apply_learning(
        self, reading: ChartReading, insight: LearningInsight, reasons: list[str],
    ) -> float:
        boost = 0.0
        detected = [p.name for p in reading.candle_patterns]

        hot = [p for p in detected if p in insight.hot_patterns]
        if hot:
            boost += LEARNING_BOOST_HOT_PATTERN
            reasons.append(f"hot_pattern={hot[0]}")

        cold = [p for p in detected if p in insight.cold_patterns]
        if cold:
            boost += LEARNING_PENALTY_COLD_PATTERN
            reasons.append(f"cold_pattern={cold[0]}")

        if reading.regime == insight.worst_regime and insight.total_trades >= 10:
            boost += LEARNING_REGIME_PENALTY
            reasons.append(f"worst_regime={reading.regime}")

        return boost

    def _build_entry_plan(self, reading: ChartReading) -> EntryPlan | None:
        if not reading.entry_zone or reading.invalidation_level is None:
            return None

        entry_price = (reading.entry_zone[0] + reading.entry_zone[1]) / 2
        stop_loss = reading.invalidation_level
        risk = abs(entry_price - stop_loss)
        if risk <= 0:
            return None

        # Gate: reject paper-thin noise stops and absurdly wide stops.
        sl_pct = risk / entry_price * 100
        if sl_pct < MIN_SL_PCT:
            return None  # invalidation too tight — noise stop, skip trade
        if sl_pct > MAX_SL_PCT:
            return None  # invalidation too wide — bad R per unit risk

        # Prefer real HTF liquidity / swing targets when they clear min RR.
        # Falls back to R-multiples when no clean structural target exists.
        targets = _select_take_profits(reading, entry_price, risk)
        tp1, tp2, tp3 = targets

        # Determine order type: MARKET if price already in zone, else LIMIT
        order_type: str = "MARKET"
        zone_width_pct = abs(reading.entry_zone[1] - reading.entry_zone[0]) / entry_price * 100
        if zone_width_pct < 0.3:
            # Very tight zone = likely already at level → MARKET
            order_type = "MARKET"

        rr = abs(tp1 - entry_price) / risk if risk > 0 else 0.0
        return EntryPlan(
            side="BUY" if reading.bias == "BULLISH" else "SELL",
            entry_price=round(entry_price, 8),
            stop_loss=round(stop_loss, 8),
            take_profit_1=round(tp1, 8),
            take_profit_2=round(tp2, 8) if tp2 is not None else None,
            take_profit_3=round(tp3, 8) if tp3 is not None else None,
            risk_reward=round(rr, 2),
            entry_zone=(round(reading.entry_zone[0], 8), round(reading.entry_zone[1], 8)),
            order_type=order_type,  # type: ignore[arg-type]
            expires_in_seconds=900.0,
        )

    def _skip(self, reading: ChartReading, reasons: list[str]) -> Decision:
        return Decision(
            action="SKIP", symbol=reading.symbol, confidence="LOW",
            confidence_score=reading.bias_confidence, reasons=reasons,
            regime=reading.regime, confluence_score=reading.confluence_score,
            timestamp=reading.timestamp,
        )

    def _confidence_level(self, score: float) -> DecisionConfidence:
        if score >= 85:
            return "HIGH"
        if score >= 70:
            return "MEDIUM"
        return "LOW"

