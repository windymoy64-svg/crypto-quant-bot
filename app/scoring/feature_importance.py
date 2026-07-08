from __future__ import annotations

from app.core.models import FeatureContribution, RuleResult


FEATURE_CATEGORIES = [
    "EMA",
    "SMA",
    "RSI",
    "MACD",
    "ATR",
    "Volume",
    "Breakout",
    "Momentum",
    "Trend",
    "Pattern",
    "Volatility",
    "SupportResistance",
    "Other",
]


class FeatureImportanceEngine:
    def calculate(self, rules: list[RuleResult]) -> list[FeatureContribution]:
        scores = {feature: 0.0 for feature in FEATURE_CATEGORIES}

        for rule in rules:
            feature = self.category_for(rule)
            scores[feature] += float(rule.score)

        total_score = sum(scores.values())
        contributions = [
            FeatureContribution(
                feature=feature,
                score=round(score, 2),
                percentage=round((score / total_score) * 100, 2) if total_score else 0.0,
            )
            for feature, score in scores.items()
            if score > 0
        ]
        return sorted(contributions, key=lambda contribution: contribution.score, reverse=True)

    def category_for(self, rule: RuleResult) -> str:
        text = f"{rule.rule_id} {rule.rule_name} {rule.reason}".lower()
        if "ema" in text:
            return "EMA"
        if "sma" in text:
            return "SMA"
        if "rsi" in text:
            return "RSI"
        if "macd" in text:
            return "MACD"
        if "atr" in text:
            return "ATR"
        if "volume" in text or "obv" in text:
            return "Volume"
        if "breakout" in text or "high" in text or "low" in text:
            return "Breakout"
        if "momentum" in text or "roc" in text or "stoch" in text:
            return "Momentum"
        if "trend" in text or "bullish" in text or "bearish" in text:
            return "Trend"
        if "pattern" in text or "candle" in text or "engulf" in text:
            return "Pattern"
        if "volatility" in text or "range" in text:
            return "Volatility"
        if "support" in text or "resistance" in text or "pivot" in text:
            return "SupportResistance"
        return "Other"