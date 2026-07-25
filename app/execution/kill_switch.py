from typing import Dict, List
from datetime import datetime, timedelta

class KillSwitch:
    """Emergency stop mechanism for trading"""
    
    def __init__(self):
        self.enabled = False
        self.activation_time: datetime = None
        self.reason: str = ""
        self.auto_activate_thresholds = {
            "max_daily_drawdown": 5.0,  # 5% max daily drawdown
            "max_consecutive_losses": 5,  # Max consecutive losing trades
            "max_position_count": 10,  # Max open positions
            "max_exposure": 75.0  # Max portfolio exposure
        }
        self.consecutive_losses = 0
        self.daily_drawdown = 0.0
        self.positions_count = 0
        self.exposure = 0.0
    
    def activate(self, reason: str):
        """Activate the kill switch"""
        self.enabled = True
        self.activation_time = datetime.now()
        self.reason = reason
        
    def deactivate(self):
        """Deactivate the kill switch"""
        self.enabled = False
        self.activation_time = None
        self.reason = ""
    
    def check_auto_activation(self) -> bool:
        """Check if auto-activation thresholds are met"""
        # Check daily drawdown
        if self.daily_drawdown >= self.auto_activate_thresholds["max_daily_drawdown"]:
            self.activate(f"Daily drawdown exceeded: {self.daily_drawdown}%")
            return True
        
        # Check consecutive losses
        if self.consecutive_losses >= self.auto_activate_thresholds["max_consecutive_losses"]:
            self.activate(f"Maximum consecutive losses reached: {self.consecutive_losses}")
            return True
        
        # Check positions count
        if self.positions_count >= self.auto_activate_thresholds["max_position_count"]:
            self.activate(f"Maximum positions count reached: {self.positions_count}")
            return True
        
        # Check exposure
        if self.exposure >= self.auto_activate_thresholds["max_exposure"]:
            self.activate(f"Maximum exposure reached: {self.exposure}%")
            return True
        
        return False
    
    def is_active(self) -> bool:
        """Check if kill switch is active"""
        return self.enabled
    
    def reset_daily_counters(self):
        """Reset daily counters"""
        self.daily_drawdown = 0.0
        self.consecutive_losses = 0
    
    def update_after_trade(self, profit_loss: float, is_win: bool):
        """Update counters after a trade"""
        if not is_win:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0
        
        self.daily_drawdown -= profit_loss  # Assuming profit_loss is negative for losses
        
    def update_positions(self, count: int, exposure: float):
        """Update positions count and exposure"""
        self.positions_count = count
        self.exposure = exposure