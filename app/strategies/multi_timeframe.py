from typing import Dict, List, Tuple
from pydantic import BaseModel

class TimeframeAnalysis(BaseModel):
    """Analysis result for a single timeframe"""
    timeframe: str
    trend: str  # BULLISH, BEARISH, NEUTRAL
    structure: str  # HH_HL, LH_LL, MIXED
    score: float
    key_levels: List[float]
    reasons: List[str]

class MultiTimeframeResult(BaseModel):
    """Result of multi-timeframe analysis"""
    overall_bias: str  # BULLISH, BEARISH, NEUTRAL
    confluence_score: float
    timeframe_results: Dict[str, TimeframeAnalysis]
    hard_gates_passed: bool
    hard_gates_failed: List[str]
    reasons: List[str]
    warnings: List[str]

class MultiTimeframeAnalyzer:
    """Analyzes multiple timeframes for trading confluence"""
    
    def __init__(self):
        # Define timeframe hierarchy and weights
        self.timeframe_hierarchy = {
            "1d": 0.40,  # Primary regime
            "4h": 0.30,  # Trend structure
            "1h": 0.20,  # Setup quality
            "15m": 0.10  # Entry timing
        }
        
        # Define hard gates for each timeframe
        self.hard_gates = {
            "1d": {
                "min_score": 40.0,
                "required_trend": ["BULLISH", "NEUTRAL"]  # Not strong bearish
            },
            "4h": {
                "min_score": 50.0,
                "required_trend": ["BULLISH", "NEUTRAL"]
            },
            "1h": {
                "min_score": 60.0
            },
            "15m": {
                "min_score": 65.0
            }
        }

    def analyze_timeframe(self, data: dict, timeframe: str) -> TimeframeAnalysis:
        """Analyze a single timeframe"""
        reasons = []
        close = data.get("close", 0)
        ema_20 = data.get("ema_20", 0)
        ema_50 = data.get("ema_50", 0)
        ema_200 = data.get("ema_200", 0)

        if close > ema_20 and ema_20 > ema_50 and ema_50 > ema_200:
            trend = "BULLISH"
            reasons.append("All EMAs aligned bullish")
        elif close < ema_20 and ema_20 < ema_50 and ema_50 < ema_200:
            trend = "BEARISH"
            reasons.append("All EMAs aligned bearish")
        else:
            trend = "NEUTRAL"
            reasons.append("Mixed EMA alignment")

        if trend == "BULLISH":
            score = 50.0
            if close > ema_20:
                score += 15.0
                reasons.append("Price above EMA20")
            if ema_20 > ema_50:
                score += 15.0
                reasons.append("EMA20 above EMA50")
            if ema_50 > ema_200:
                score += 20.0
                reasons.append("EMA50 above EMA200")
            rsi = data.get("rsi_14", 50)
            if 50 <= rsi <= 70:
                score += 10.0
                reasons.append("RSI in healthy range")
        elif trend == "BEARISH":
            score = 40.0
            reasons.append("EMA stack bearish")
        else:
            # Mixed alignment: baseline 50, plus long-term trend context only.
            score = 50.0
            if ema_50 > ema_200:
                score += 20.0
                reasons.append("EMA50 above EMA200")

        return TimeframeAnalysis(
            timeframe=timeframe,
            trend=trend,
            structure="MIXED",
            score=min(100.0, max(0.0, score)),
            key_levels=[ema_20, ema_50, ema_200],
            reasons=reasons
        )

    def analyze_multi_timeframe(self, multi_tf_data: dict[str, dict]) -> MultiTimeframeResult:
        """Analyze multiple timeframes and determine overall bias"""
        tf_results: dict[str, TimeframeAnalysis] = {}
        reasons: list[str] = []
        warnings: list[str] = []
        hard_fails: list[str] = []

        for tf, data in multi_tf_data.items():
            if tf not in self.timeframe_hierarchy:
                continue
            result = self.analyze_timeframe(data, tf)
            tf_results[tf] = result

            gate = self.hard_gates.get(tf, {})
            # Hanya timeframe regime (1d) yang memblokir sinyal; timeframe lebih
            # rendah dicatat sebagai warning supaya satu timeframe lemah tidak
            # membatalkan bias keseluruhan.
            hard = tf == "1d"
            if result.score < gate.get("min_score", 0):
                if hard:
                    hard_fails.append(f"{tf}_score_below_min")
                warnings.append(f"{tf} score {result.score:.1f} < min {gate['min_score']}")
            req_trend = gate.get("required_trend", [])
            if req_trend and result.trend not in req_trend:
                if hard:
                    hard_fails.append(f"{tf}_trend_not_allowed")
                warnings.append(f"{tf} trend {result.trend} not allowed")

        conflu = sum(
            tf_results[tf].score * self.timeframe_hierarchy[tf]
            for tf in tf_results
        )

        bulls = sum(1 for r in tf_results.values() if r.trend == "BULLISH")
        bears = sum(1 for r in tf_results.values() if r.trend == "BEARISH")

        if bulls > bears and conflu >= 60:
            bias = "BULLISH"
            reasons.append("Multi-timeframe bullish confluence")
        elif bears > bulls and conflu >= 60:
            bias = "BEARISH"
            reasons.append("Multi-timeframe bearish confluence")
        else:
            bias = "NEUTRAL"
            reasons.append("Mixed multi-timeframe signals")

        for r in tf_results.values():
            reasons.extend(f"[{r.timeframe}] {x}" for x in r.reasons)

        return MultiTimeframeResult(
            overall_bias=bias,
            confluence_score=conflu,
            timeframe_results=tf_results,
            hard_gates_passed=len(hard_fails) == 0,
            hard_gates_failed=hard_fails,
            reasons=reasons,
            warnings=warnings
        )
