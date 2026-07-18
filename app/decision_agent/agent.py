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

DEFAULT_MIN_CONFLUENCE = 60.0
DEFAULT_MIN_CONFIDENCE_ENTRY = 70.0
DEFAULT_MIN_RR = 2.0
LEARNING_BOOST_HOT_PATTERN = 8.0
LEARNING_PENALTY_COLD_PATTERN = -12.0
LEARNING_REGIME_PENALTY = -10.0
HOLD_INVALIDATION_THRESHOLD = 40.0


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
        reasons.insert(0, f"bias={reading.bias}")
        reasons.append(f"confluence={reading.confluence_score:.0f}")
        reasons.append(f"regime={reading.regime}")

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
        return Decision(
            action="HOLD", symbol=reading.symbol, confidence="MEDIUM",
            confidence_score=reading.bias_confidence, reasons=reasons,
            regime=reading.regime, confluence_score=reading.confluence_score,
            timestamp=reading.timestamp,
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

        if reading.bias == "BULLISH":
            tp1 = entry_price + risk * 2
            tp2 = entry_price + risk * 3
            tp3 = entry_price + risk * 4
        else:
            tp1 = entry_price - risk * 2
            tp2 = entry_price - risk * 3
            tp3 = entry_price - risk * 4

        return EntryPlan(
            side="BUY" if reading.bias == "BULLISH" else "SELL",
            entry_price=round(entry_price, 8),
            stop_loss=round(stop_loss, 8),
            take_profit_1=round(tp1, 8),
            take_profit_2=round(tp2, 8),
            take_profit_3=round(tp3, 8),
            risk_reward=2.0,
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

