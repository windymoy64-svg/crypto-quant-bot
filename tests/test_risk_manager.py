import unittest
from app.risk.risk_settings import RiskSettings
from app.risk.risk_manager import RiskManager

class TestRiskManager(unittest.TestCase):
    
    def setUp(self):
        # Create basic risk settings for testing
        self.risk_settings = RiskSettings(
            risk_per_trade_percent=0.5,
            max_position_size_percent=15.0,
            max_exposure_percent=100.0,
            max_open_positions=20,
            max_daily_drawdown_percent=5.0,
            min_risk_reward=1.5,
            min_atr_percent=0.5,
            max_atr_percent=5.0
        )
        self.risk_manager = RiskManager(self.risk_settings)
    
    def test_hard_gate_pass(self):
        """Test that valid opportunities pass hard gates"""
        data = {
            "data_freshness_seconds": 60,
            "spread_pct": 0.1,
            "volume_24h_usdt": 1000000.0,
            "stop_loss": 45000,
            "risk_reward_ratio": 2.0
        }
        
        passed, failed_gates, warnings = self.risk_manager.check_hard_gates(data)
        
        self.assertTrue(passed)
        self.assertEqual(len(failed_gates), 0)
        self.assertEqual(len(warnings), 0)
    
    def test_hard_gate_failures(self):
        """Test that invalid opportunities fail hard gates"""
        # Test stale data failure
        data = {
            "data_freshness_seconds": 600,  # 10 minutes, exceeds 5 minute limit
            "spread_pct": 0.1,
            "volume_24h_usdt": 1000000.0,
            "stop_loss": 45000,
            "risk_reward_ratio": 2.0
        }
        
        passed, failed_gates, warnings = self.risk_manager.check_hard_gates(data)
        
        self.assertFalse(passed)
        self.assertIn("STALE_DATA", failed_gates)
        self.assertTrue(any("Market data is stale" in warning for warning in warnings))
        
        # Test high spread failure
        data = {
            "data_freshness_seconds": 60,
            "spread_pct": 0.5,  # High spread
            "volume_24h_usdt": 1000000.0,
            "stop_loss": 45000,
            "risk_reward_ratio": 2.0
        }
        
        passed, failed_gates, warnings = self.risk_manager.check_hard_gates(data)
        
        self.assertFalse(passed)
        self.assertIn("HIGH_SPREAD", failed_gates)
    
    def test_soft_penalties(self):
        """Test application of soft penalties"""
        data = {
            "rsi_14": 80,  # Overbought
            "price_ema_distance": 10.0,  # Far from EMA
            "volume_ratio_20": 0.5,  # Low volume
            "distance_to_resistance_pct": 1.0,  # Close to resistance
            "btc_regime": "bearish"  # Bearish BTC
        }
        
        adjusted_score, penalties, warnings = self.risk_manager.apply_soft_penalties(data, 100.0)
        
        # Check that penalties were applied
        self.assertGreater(len(penalties), 0)
        self.assertLess(adjusted_score, 100.0)
        
        # Check specific penalties
        self.assertIn("RSI_HOT", penalties)
        self.assertIn("PRICE_FAR_FROM_EMA", penalties)
        self.assertIn("WEAK_VOLUME", penalties)
        self.assertIn("NEAR_RESISTANCE", penalties)
        self.assertIn("BTC_BEARISH_REGIME", penalties)
        
        # Check warnings
        self.assertTrue(any("RSI approaching overbought" in warning for warning in warnings))
        self.assertTrue(any("Price extended from moving average" in warning for warning in warnings))
    
    def test_complete_risk_check(self):
        """Test complete risk check process"""
        # Valid data that should pass
        valid_data = {
            "data_freshness_seconds": 60,
            "spread_pct": 0.1,
            "volume_24h_usdt": 1000000.0,
            "stop_loss": 45000,
            "risk_reward_ratio": 2.0,
            "rsi_14": 60,
            "price_ema_distance": 2.0,
            "volume_ratio_20": 1.5
        }
        
        result = self.risk_manager.check_opportunity(valid_data, 80.0)
        
        self.assertTrue(result.passed)
        self.assertEqual(len(result.hard_gates_failed), 0)
        # Semua indikator berada di sisi aman ambang soft penalty.
        self.assertEqual(result.soft_penalties_applied, {})
        self.assertEqual(result.total_penalty, 0.0)
        
        # Invalid data that should fail
        invalid_data = {
            "data_freshness_seconds": 600,
            "spread_pct": 0.1,
            "volume_24h_usdt": 1000000.0,
            "stop_loss": 45000,
            "risk_reward_ratio": 2.0
        }
        
        result = self.risk_manager.check_opportunity(invalid_data, 80.0)
        
        self.assertFalse(result.passed)
        self.assertGreater(len(result.hard_gates_failed), 0)

if __name__ == '__main__':
    unittest.main()