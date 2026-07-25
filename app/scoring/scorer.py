import pandas as pd
from typing import Dict, List, Tuple
from pydantic import BaseModel

class ScoreResult(BaseModel):
    """Result of scoring a trading opportunity"""
    symbol: str
    timeframe: str
    total_score: float
    max_possible_score: float
    confluence_score: float  # Renamed from confidence
    category_scores: Dict[str, float]
    reasons: List[str]
    warnings: List[str]
    action: str  # BUY, WATCH, SKIP
    data_quality: str  # GOOD, WARNING, BAD

class ScoringEngine:
    """Scoring engine that calculates confluence scores for trading opportunities"""
    
    def __init__(self):
        # Define category weights
        self.category_weights = {
            "trend": 0.30,
            "momentum": 0.20,
            "volume": 0.20,
            "volatility": 0.15,
            "liquidity": 0.10,
            "relative_strength": 0.05
        }
        
        # Define quality gates (minimum percentage scores)
        self.quality_gates = {
            "trend": 0.65,
            "momentum": 0.55,
            "volume": 0.40,
            "volatility": 0.30,
            "liquidity": 0.70,
            "relative_strength": 0.50
        }
    
    def normalize_category_score(self, earned_points: float, max_points: float) -> float:
        """Normalize category score to 0-100 scale"""
        if max_points <= 0:
            return 0.0
        return min(100.0, max(0.0, (earned_points / max_points) * 100))
    
    def calculate_rsi_score(self, rsi: float) -> float:
        """Calculate normalized RSI score"""
        if 50 <= rsi <= 65:
            return 100.0
        elif 45 <= rsi < 50 or 65 < rsi <= 72:
            return 70.0
        elif 35 <= rsi < 45:
            return 40.0
        else:
            return 10.0
    def calculate_ema_score(self, close: float, ema_20: float, ema_50: float, ema_200: float) -> Tuple[float, List[str]]:
        """Calculate EMA alignment score"""
        score = 0.0
        reasons = []
        
        if close > ema_20 > ema_50:
            score += 30.0
            reasons.append("Price above EMA20 and EMA50")
            
        if ema_50 > ema_200:
            score += 20.0
            reasons.append("Medium-term trend bullish")
            
        if close > ema_20 > ema_50 > ema_200:
            score += 25.0
            reasons.append("All EMAs aligned bullish")
            
        return score, reasons
    
    def calculate_volume_score(self, volume_ratio: float) -> float:
        """Calculate normalized volume score"""
        if volume_ratio >= 2.0:
            return 100.0
        elif volume_ratio >= 1.5:
            return 80.0
        elif volume_ratio >= 1.2:
            return 60.0
        elif volume_ratio >= 1.0:
            return 40.0
        else:
            return 20.0
    
    def score_opportunity(self, data: Dict) -> ScoreResult:
        """Score a trading opportunity based on multiple factors"""
        # Initialize category scores
        category_scores = {
            "trend": 0.0,
            "momentum": 0.0,
            "volume": 0.0,
            "volatility": 0.0,
            "liquidity": 0.0,
            "relative_strength": 0.0
        }
        
        max_category_scores = {
            "trend": 75.0,
            "momentum": 60.0,
            "volume": 100.0,
            "volatility": 50.0,
            "liquidity": 50.0,
            "relative_strength": 50.0
        }
        
        reasons = []
        warnings = []
        
        # Trend scoring
        ema_score, ema_reasons = self.calculate_ema_score(
            data.get("close", 0),
            data.get("ema_20", 0),
            data.get("ema_50", 0),
            data.get("ema_200", 0)
        )
        category_scores["trend"] = ema_score
        reasons.extend(ema_reasons)
        
        # Momentum scoring
        rsi = data.get("rsi_14", 50)
        rsi_score = self.calculate_rsi_score(rsi)
        category_scores["momentum"] = rsi_score
        
        if 65 < rsi <= 75:
            reasons.append("RSI in healthy bullish range")
        elif 75 < rsi <= 80:
            warnings.append("RSI approaching overbought")
        elif rsi > 80:
            warnings.append("RSI overbought")
        
        # Volume scoring
        volume_ratio = data.get("volume_ratio_20", 1.0)
        volume_score = self.calculate_volume_score(volume_ratio)
        category_scores["volume"] = volume_score
        
        if volume_ratio >= 1.5:
            reasons.append(f"Volume {volume_ratio:.1f}x average")
        elif volume_ratio < 1.0:
            warnings.append("Below average volume")
        
        # Normalize all category scores
        normalized_scores = {}
        for category, score in category_scores.items():
            normalized_scores[category] = self.normalize_category_score(
                score, max_category_scores[category]
            )
        
        # Check quality gates
        failed_gates = []
        for category, min_score in self.quality_gates.items():
            if normalized_scores[category] < min_score * 100:
                failed_gates.append(category)
        
        # Calculate total score
        total_score = 0.0
        for category, score in normalized_scores.items():
            total_score += score * self.category_weights[category]
        
        # Determine action based on quality gates and total score
        if len(failed_gates) > 2:
            action = "SKIP"
        elif total_score >= 75:
            action = "BUY"
        elif total_score >= 60:
            action = "WATCH"
        else:
            action = "SKIP"
        
        # Data quality assessment
        if data.get("spread_pct", 0) > 0.2:
            data_quality = "BAD"
            warnings.append("High spread")
        elif data.get("spread_pct", 0) > 0.1:
            data_quality = "WARNING"
            warnings.append("Moderate spread")
        else:
            data_quality = "GOOD"
        
        return ScoreResult(
            symbol=data.get("symbol", "UNKNOWN"),
            timeframe=data.get("timeframe", "15m"),
            total_score=total_score,
            max_possible_score=100.0,
            confluence_score=total_score,  # Same as total for now
            category_scores=normalized_scores,
            reasons=reasons,
            warnings=warnings,
            action=action,
            data_quality=data_quality
        )