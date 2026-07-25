import unittest
from config.backtest_config import BacktestConfig
from app.risk.risk_settings import create_risk_settings_from_config

class TestRiskSettings(unittest.TestCase):
    
    def test_create_risk_settings_from_config(self):
        """Test that risk settings are created correctly from config"""
        config = BacktestConfig()
        risk_settings = create_risk_settings_from_config(config)
        
        # Verify that the correct values are used
        self.assertEqual(risk_settings.max_position_size_percent, 15.0)
        self.assertEqual(risk_settings.risk_per_trade_percent, 0.5)
        self.assertEqual(risk_settings.max_exposure_percent, 100.0)
        self.assertEqual(risk_settings.max_open_positions, 20)
        
        # Verify that changing config values affects the risk settings
        config.max_position_size_percent = 10.0
        risk_settings = create_risk_settings_from_config(config)
        self.assertEqual(risk_settings.max_position_size_percent, 10.0)

if __name__ == '__main__':
    unittest.main()