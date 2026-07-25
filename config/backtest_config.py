from pydantic import BaseModel
from typing import Optional

class BacktestConfig(BaseModel):
    """Configuration for backtesting"""
    
    # Position sizing
    position_size_percent: float = 15.0
    max_position_size_percent: float = 15.0
    
    # Risk management
    risk_per_trade_percent: float = 0.5
    max_exposure_percent: float = 100.0
    max_open_positions: int = 20
    max_daily_drawdown_percent: float = 5.0
    
    # Trade parameters
    min_risk_reward: float = 1.5
    min_atr_percent: float = 0.5
    max_atr_percent: float = 5.0
    
    # Slippage and fees
    maker_fee_percent: float = 0.02
    taker_fee_percent: float = 0.04
    slippage_percent: float = 0.05
    spread_percent: float = 0.02
    latency_seconds: float = 0.1
    
    # Testing parameters
    start_date: str = "2023-01-01"
    end_date: str = "2024-01-01"
    timeframes: list[str] = ["15m", "1h", "4h", "1d"]
    
    # Data parameters
    fallback_to_sample_data: bool = False
    max_candle_gap_hours: int = 24