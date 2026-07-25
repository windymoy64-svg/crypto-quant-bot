from pydantic import BaseModel
from typing import Optional

class RiskSettings(BaseModel):
    """Risk management settings for trading"""
    
    # Position sizing limits
    risk_per_trade_percent: float
    max_position_size_percent: float
    max_exposure_percent: float
    max_open_positions: int
    
    # Daily limits
    max_daily_drawdown_percent: float
    
    # Trade quality requirements
    min_risk_reward: float
    min_atr_percent: float
    max_atr_percent: float
    
    # Data quality requirements
    max_allowed_spread_percent: float = 0.2
    min_required_volume_usdt: float = 100000.0
    data_freshness_max_seconds: int = 300  # 5 minutes
    
    # Hard risk gates - signals failing these are rejected outright
    hard_risk_gates: dict = {
        "STALE_DATA": True,
        "HIGH_SPREAD": True,
        "LOW_LIQUIDITY": True,
        "INVALID_STOP_LOSS": True,
        "MIN_RISK_REWARD_FAILED": True,
        "DAILY_DRAWDOWN_EXCEEDED": True,
        "MAX_POSITIONS_REACHED": True
    }
    
    # Soft penalties - reduce ranking but don't reject outright
    soft_penalties: dict = {
        "RSI_HOT": 5.0,
        "PRICE_FAR_FROM_EMA": 3.0,
        "WEAK_VOLUME": 4.0,
        "NEAR_RESISTANCE": 3.0,
        "BTC_BEARISH_REGIME": 7.0
    }

def create_risk_settings_from_config(config) -> RiskSettings:
    """Create RiskSettings instance from configuration"""
    return RiskSettings(
        risk_per_trade_percent=config.risk_per_trade_percent,
        max_position_size_percent=config.max_position_size_percent,  # FIXED: Was using wrong config field
        max_exposure_percent=config.max_exposure_percent,
        max_open_positions=config.max_open_positions,
        max_daily_drawdown_percent=config.max_daily_drawdown_percent,
        min_risk_reward=config.min_risk_reward,
        min_atr_percent=config.min_atr_percent,
        max_atr_percent=config.max_atr_percent
    )