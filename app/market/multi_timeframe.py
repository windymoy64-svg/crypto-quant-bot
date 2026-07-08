from __future__ import annotations

from dataclasses import asdict, dataclass

from app.core.models import FeatureContribution, RuleResult
from app.features.builder import build_features
from app.market.data_service import MarketDataService
from app.market.regime import MarketRegime, MarketRegimeEngine
from app.scoring.dynamic_weights import RuleWeightProfile
from app.scoring.engine import ScoreEngine
from app.scoring.feature_importance import FeatureImportanceEngine
from app.signals.builder import build_signal


TIMEFRAME_WEIGHTS = {
    "5m": 0.10,
    "15m": 0.15,
    "1h": 0.25,
    "4h": 0.30,
    "1d": 0.20,
}


@dataclass(frozen=True)
class TimeframeSignal:
    timeframe: str
    score: float
    confidence: float
    action: str
    entry: float
    stop_loss: float
    take_profit: list[float]
    rules: list[RuleResult]

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["rules"] = [rule.to_dict() for rule in self.rules]
        return payload


@dataclass(frozen=True)
class MultiTimeframeResult:
    symbol: str
    market_regime: MarketRegime
    weight_profile: RuleWeightProfile | None
    signals: list[TimeframeSignal]
    rules: list[RuleResult]
    feature_importance: list[FeatureContribution]
    final_score: float
    final_confidence: float
    trend_alignment: str
    overall_action: str

    def to_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "market_regime": self.market_regime.to_dict(),
            "weight_profile": self.weight_profile.to_dict() if self.weight_profile else None,
            "signals": [signal.to_dict() for signal in self.signals],
            "rules": [rule.to_dict() for rule in self.rules],
            "feature_importance": [contribution.to_dict() for contribution in self.feature_importance],
            "final_score": self.final_score,
            "final_confidence": self.final_confidence,
            "trend_alignment": self.trend_alignment,
            "overall_action": self.overall_action,
        }


class MultiTimeframeScanner:
    def __init__(
        self,
        exchange: str = "binance",
        *,
        fallback_to_sample_data: bool = True,
        rules_path: str = "configs/rules.json",
        weights_path: str = "configs/rule_weights.json",
    ) -> None:
        self.market_data = MarketDataService(exchange=exchange, fallback_to_sample_data=fallback_to_sample_data)
        self.score_engine = ScoreEngine.from_json(rules_path, weights_path=weights_path)
        self.regime_engine = MarketRegimeEngine()
        self.feature_importance_engine = FeatureImportanceEngine()

    def scan_symbol(
        self,
        symbol: str,
        *,
        timeframes: list[str] | None = None,
        limit: int = 100,
    ) -> MultiTimeframeResult:
        selected_timeframes = timeframes or list(TIMEFRAME_WEIGHTS)
        signals: list[TimeframeSignal] = []
        market_regime: MarketRegime | None = None
        weight_profile: RuleWeightProfile | None = None
        primary_rules: list[RuleResult] = []

        for timeframe in selected_timeframes:
            loaded = self.market_data.fetch_ohlcv(symbol=symbol, timeframe=timeframe, limit=limit)
            features = build_features(loaded.candles)
            if market_regime is None:
                market_regime = self.regime_engine.analyze(features)
                weight_profile = self.score_engine.weight_profile_for(market_regime)
            score = self.score_engine.score(loaded.candles, market_regime=market_regime)
            if not primary_rules:
                primary_rules = score.rules
            trading_signal = build_signal(symbol=symbol, candles=loaded.candles, score=score)
            signals.append(
                TimeframeSignal(
                    timeframe=timeframe,
                    score=trading_signal.score,
                    confidence=trading_signal.confidence,
                    action=trading_signal.action,
                    entry=trading_signal.entry,
                    stop_loss=trading_signal.stop_loss,
                    take_profit=trading_signal.take_profit,
                    rules=score.rules,
                )
            )

        final_score = self._weighted_average(signals, "score")
        final_confidence = self._weighted_average(signals, "confidence")
        return MultiTimeframeResult(
            symbol=symbol,
            market_regime=market_regime or self.regime_engine.analyze({}),
            weight_profile=weight_profile,
            signals=signals,
            rules=primary_rules,
            feature_importance=self.feature_importance_engine.calculate(primary_rules),
            final_score=final_score,
            final_confidence=final_confidence,
            trend_alignment=self._trend_alignment(signals),
            overall_action=self._overall_action(final_score),
        )

    def scan_symbols(
        self,
        symbols: list[str],
        *,
        timeframes: list[str] | None = None,
        limit: int = 100,
    ) -> list[MultiTimeframeResult]:
        return [self.scan_symbol(symbol=symbol, timeframes=timeframes, limit=limit) for symbol in symbols]

    def _weighted_average(self, signals: list[TimeframeSignal], field: str) -> float:
        total_weight = sum(TIMEFRAME_WEIGHTS.get(signal.timeframe, 0.0) for signal in signals)
        if not signals or total_weight == 0:
            return 0.0
        weighted_total = sum(float(getattr(signal, field)) * TIMEFRAME_WEIGHTS.get(signal.timeframe, 0.0) for signal in signals)
        return round(weighted_total / total_weight, 2)

    def _trend_alignment(self, signals: list[TimeframeSignal]) -> str:
        bullish = sum(1 for signal in signals if signal.score >= 90)
        bearish = sum(1 for signal in signals if signal.score < 85)
        total = len(signals)

        if total and bullish == total:
            return "STRONG_BULLISH"
        if bullish >= 3 and bearish <= 1:
            return "BULLISH"
        if total and bearish == total:
            return "STRONG_BEARISH"
        if bearish >= 3 and bullish <= 1:
            return "BEARISH"
        return "MIXED"

    def _overall_action(self, final_score: float) -> str:
        if final_score >= 95:
            return "BUY_NOW"
        if final_score >= 90:
            return "BUY"
        if final_score >= 85:
            return "WATCH"
        return "IGNORE"