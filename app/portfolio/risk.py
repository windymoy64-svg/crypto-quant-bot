from typing import List, Dict
from app.data.models import Position, Trade
from app.risk.manager import RiskSettings, RiskManager
from app.risk.metrics import calculate_correlation_matrix

class PortfolioRisk:
    """Manages portfolio risk"""
    
    def __init__(self, risk_settings: RiskSettings, risk_manager: RiskManager):
        self.risk_settings = risk_settings
        self.risk_manager = risk_manager
        self.positions: List[Position] = []
        self.trades: List[Trade] = []
        self.correlation_matrix: Dict = {}
    
    def add_position(self, position: Position):
        """Add a new position to the portfolio"""
        self.positions.append(position)
        self.update_correlation()
    
    def close_position(self, position_id: str):
        """Close a position and remove from portfolio"""
        self.positions = [pos for pos in self.positions if pos.id != position_id]
        self.update_correlation()
    
    def update_correlation(self):
        """Update the correlation matrix based on current positions"""
        if len(self.positions) < 2:
            self.correlation_matrix = {}
            return
        
        # Collect price data for each symbol
        price_data = {}
        for position in self.positions:
            if position.symbol not in price_data:
                price_data[position.symbol] = []
            price_data[position.symbol].append(position.entry_price)
        
        # Calculate correlation matrix
        self.correlation_matrix = calculate_correlation_matrix(price_data)
    
    def get_correlation(self, symbol1: str, symbol2: str) -> float:
        """Get correlation between two symbols"""
        return self.correlation_matrix.get(symbol1, {}).get(symbol2, 0.0)
    
    def get_total_exposure(self) -> float:
        """Calculate total exposure of the portfolio"""
        exposure = sum(pos.quantity * pos.entry_price for pos in self.positions)
        return exposure
    
    def check_risk(self) -> bool:
        """Check overall portfolio risk"""
        total_exposure = self.get_total_exposure()
        max_exposure = self.risk_settings.max_exposure_percent * sum(pos.quantity * pos.entry_price for pos in self.positions)
        
        if total_exposure > max_exposure:
            return False
        
        return True
    
    def apply_circuit_breaker(self) -> bool:
        """Apply circuit breaker if necessary"""
        if self.risk_manager.daily_drawdown > self.risk_settings.max_daily_drawdown_percent:
            return False
        
        return True