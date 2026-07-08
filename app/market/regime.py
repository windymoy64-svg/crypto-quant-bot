from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class MarketRegime:
    regime: str
    trend_strength: str
    volatility_state: str
    volume_state: str
    confidence: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class MarketRegimeEngine:
    def analyze(self, features: dict[str, float | bool]) -> MarketRegime:
        bullish_points = self._bullish_points(features)
        bearish_points = self._bearish_points(features)
        atr_percent = float(features.get("atr_percent", 0.0))
        volume_ratio = float(features.get("volume_ratio", 1.0))

        trend_strength = self._trend_strength(bullish_points, bearish_points)
        volatility_state = self._volatility_state(atr_percent)
        volume_state = self._volume_state(volume_ratio)
        regime = self._regime(bullish_points, bearish_points, volatility_state)
        confidence = self._confidence(bullish_points, bearish_points, volatility_state, volume_state)

        return MarketRegime(
            regime=regime,
            trend_strength=trend_strength,
            volatility_state=volatility_state,
            volume_state=volume_state,
            confidence=confidence,
        )

    def _bullish_points(self, features: dict[str, float | bool]) -> int:
        checks = [
            bool(features.get("ema20_gt_ema50")),
            bool(features.get("ema50_gt_ema200")),
            bool(features.get("price_gt_ema20")),
            bool(features.get("macd_bullish")),
            float(features.get("rsi", 50.0)) >= 55,
        ]
        return sum(1 for check in checks if check)

    def _bearish_points(self, features: dict[str, float | bool]) -> int:
        rsi_value = float(features.get("rsi", 50.0))
        checks = [
            not bool(features.get("ema20_gt_ema50")),
            not bool(features.get("ema50_gt_ema200")),
            not bool(features.get("price_gt_ema20")),
            not bool(features.get("macd_bullish")),
            rsi_value <= 45,
        ]
        return sum(1 for check in checks if check)

    def _trend_strength(self, bullish_points: int, bearish_points: int) -> str:
        edge = abs(bullish_points - bearish_points)
        if edge >= 4:
            return "STRONG"
        if edge >= 2:
            return "MODERATE"
        return "WEAK"

    def _volatility_state(self, atr_percent: float) -> str:
        if atr_percent >= 3.0:
            return "HIGH"
        if atr_percent <= 0.5:
            return "LOW"
        return "NORMAL"

    def _volume_state(self, volume_ratio: float) -> str:
        if volume_ratio >= 1.25:
            return "HIGH"
        if volume_ratio <= 0.75:
            return "LOW"
        return "NORMAL"

    def _regime(self, bullish_points: int, bearish_points: int, volatility_state: str) -> str:
        if volatility_state == "HIGH":
            return "HIGH_VOLATILITY"
        if volatility_state == "LOW" and abs(bullish_points - bearish_points) <= 1:
            return "LOW_VOLATILITY"
        if bullish_points >= 4 and bullish_points > bearish_points:
            return "TRENDING_BULLISH"
        if bearish_points >= 4 and bearish_points > bullish_points:
            return "TRENDING_BEARISH"
        if abs(bullish_points - bearish_points) <= 1:
            return "RANGING"
        return "MIXED"

    def _confidence(self, bullish_points: int, bearish_points: int, volatility_state: str, volume_state: str) -> float:
        edge = abs(bullish_points - bearish_points)
        confidence = 45.0 + (edge * 10.0)
        if volatility_state in {"HIGH", "LOW"}:
            confidence += 7.5
        if volume_state != "NORMAL":
            confidence += 5.0
        return round(min(confidence, 95.0), 2)