from pydantic import BaseModel
from typing import Optional

class LiveTradingConfig(BaseModel):
    """Configuration for live trading"""
    
    # Core settings
    enabled: bool = False  # Master switch - deny by default
    short_enabled: bool = False  # Short execution must be explicit
    paper_trading_only: bool = True  # Start with paper trading
    
    # Risk limits
    max_positions: int = 5
    max_orders_per_day: int = 20
    cooldown_minutes: int = 60
    max_daily_drawdown_percent: float = 5.0
    
    # Execution parameters
    idempotency_enabled: bool = True
    idempotency_ttl_seconds: int = 3600
    manual_approval_required: bool = True
    
    # API key requirements
    require_no_withdrawal_api_key: bool = True
    require_kill_switch: bool = True
    
    # Canary testing
    canary_position_size_usdt: float = 10.0
    canary_max_trades: int = 5