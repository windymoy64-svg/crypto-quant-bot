from typing import Dict, List, Tuple
from pydantic import BaseModel

class RiskCheckResult(BaseModel):
    """Result of risk check for a trading opportunity"""
    passed: bool
    hard_gates_failed: List[str]
    soft_penalties_applied: Dict[str, float]
    total_penalty: float
    warnings: List[str]

class RiskManager:
    """Risk manager with hard gates and soft penalties"""
    
    def __init__(self, risk_settings):
        self.settings = risk_settings
    
    def check_hard_gates(self, data: Dict) -> Tuple[bool, List[str], List[str]]:
        """Check hard risk gates that reject trades outright"""
        failed_gates = []
        warnings = []
        
        # Check stale data
        if data.get("data_freshness_seconds", 0) > self.settings.data_freshness_max_seconds:
            if self.settings.hard_risk_gates.get("STALE_DATA", True):
                failed_gates.append("STALE_DATA")
                warnings.append("Market data is stale")
        
        # Check spread
        if data.get("spread_pct", 0) > self.settings.max_allowed_spread_percent:
            if self.settings.hard_risk_gates.get("HIGH_SPREAD", True):
                failed_gates.append("HIGH_SPREAD")
                warnings.append(f"Spread too high: {data.get('spread_pct', 0)*100:.2f}%")
        
        # Check liquidity
        if data.get("volume_24h_usdt", 0) < self.settings.min_required_volume_usdt:
            if self.settings.hard_risk_gates.get("LOW_LIQUIDITY", True):
                failed_gates.append("LOW_LIQUIDITY")
                warnings.append("Insufficient liquidity")
        
        # Check stop-loss validity
        if data.get("stop_loss", 0) <= 0:
            if self.settings.hard_risk_gates.get("INVALID_STOP_LOSS", True):
                failed_gates.append("INVALID_STOP_LOSS")
                warnings.append("Invalid stop-loss level")
        
        # Check risk/reward
        if data.get("risk_reward_ratio", 0) < self.settings.min_risk_reward:
            if self.settings.hard_risk_gates.get("MIN_RISK_REWARD_FAILED", True):
                failed_gates.append("MIN_RISK_REWARD_FAILED")
                warnings.append(f"Risk/reward below minimum: {data.get('risk_reward_ratio', 0):.1f}")
        
        return len(failed_gates) == 0, failed_gates, warnings
    
    def apply_soft_penalties(self, data: Dict, base_score: float) -> Tuple[float, Dict[str, float], List[str]]:
        """Apply soft penalties that reduce score but don't reject"""
        penalties = {}
        warnings = []
        total_penalty = 0.0
        
        # RSI penalty
        if data.get("rsi_14", 50) > 75:
            penalty = self.settings.soft_penalties.get("RSI_HOT", 5.0)
            penalties["RSI_HOT"] = penalty
            total_penalty += penalty
            warnings.append("RSI approaching overbought")
        
        # Price far from EMA
        if data.get("price_ema_distance", 0) > 5.0:
            penalty = self.settings.soft_penalties.get("PRICE_FAR_FROM_EMA", 3.0)
            penalties["PRICE_FAR_FROM_EMA"] = penalty
            total_penalty += penalty
            warnings.append("Price extended from moving average")
        
        # Weak volume
        if data.get("volume_ratio_20", 1.0) < 1.2:
            penalty = self.settings.soft_penalties.get("WEAK_VOLUME", 4.0)
            penalties["WEAK_VOLUME"] = penalty
            total_penalty += penalty
            warnings.append("Volume below average")
        
        # Near resistance
        if data.get("distance_to_resistance_pct", 100) < 2.0:
            penalty = self.settings.soft_penalties.get("NEAR_RESISTANCE", 3.0)
            penalties["NEAR_RESISTANCE"] = penalty
            total_penalty += penalty
            warnings.append("Very close to resistance level")
        
        # BTC bearish regime
        if data.get("btc_regime", "neutral") == "bearish":
            penalty = self.settings.soft_penalties.get("BTC_BEARISH_REGIME", 7.0)
            penalties["BTC_BEARISH_REGIME"] = penalty
            total_penalty += penalty
            warnings.append("BTC in bearish regime")
        
        adjusted_score = max(0, base_score - total_penalty)
        return adjusted_score, penalties, warnings
    
    def check_opportunity(self, data: Dict, base_score: float) -> RiskCheckResult:
        """Comprehensive risk check for a trading opportunity"""
        # First check hard gates
        passed_hard, hard_gates, hard_warnings = self.check_hard_gates(data)
        
        if not passed_hard:
            return RiskCheckResult(
                passed=False,
                hard_gates_failed=hard_gates,
                soft_penalties_applied={},
                total_penalty=0.0,
                warnings=hard_warnings
            )
        
        # Then apply soft penalties
        adjusted_score, soft_penalties, soft_warnings = self.apply_soft_penalties(data, base_score)
        
        all_warnings = hard_warnings + soft_warnings
        
        return RiskCheckResult(
            passed=True,
            hard_gates_failed=[],
            soft_penalties_applied=soft_penalties,
            total_penalty=sum(soft_penalties.values()),
            warnings=all_warnings
        )
