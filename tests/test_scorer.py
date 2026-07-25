import unittest
from app.scoring.scorer import ScoringEngine, ScoreResult

class TestScorer(unittest.TestCase):
    
    def setUp(self):
        self.scorer = ScoringEngine()
    
    def test_normalize_category_score(self):
        """Test category score normalization"""
        # Test normal case
        self.assertEqual(self.scorer.normalize_category_score(50, 100), 50.0)
        
        # Test edge cases
        self.assertEqual(self.scorer.normalize_category_score(0, 100), 0.0)
        self.assertEqual(self.scorer.normalize_category_score(100, 100), 100.0)
        
        # Test boundary conditions
        self.assertEqual(self.scorer.normalize_category_score(-10, 100), 0.0)
        self.assertEqual(self.scorer.normalize_category_score(110, 100), 100.0)
        
        # Test zero max points
        self.assertEqual(self.scorer.normalize_category_score(50, 0), 0.0)
    
    def test_calculate_rsi_score(self):
        """Test RSI score calculation"""
        # Test bullish RSI range
        self.assertEqual(self.scorer.calculate_rsi_score(60), 100.0)
        
        # Test near neutral RSI
        self.assertEqual(self.scorer.calculate_rsi_score(45), 40.0)
        self.assertEqual(self.scorer.calculate_rsi_score(75), 70.0)
        
        # Test extreme RSI values
        self.assertEqual(self.scorer.calculate_rsi_score(30), 10.0)
        self.assertEqual(self.scorer.calculate_rsi_score(85), 10.0)
    
    def test_calculate_ema_score(self):
        """Test EMA alignment scoring"""
        # Test perfect bullish alignment
        score, reasons = self.scorer.calculate_ema_score(110, 105, 100, 95)
        self.assertEqual(score, 75.0)  # 30 + 20 + 25
        self.assertIn("All EMAs aligned bullish", reasons)
        
        # Test partial alignment
        score, reasons = self.scorer.calculate_ema_score(105, 100, 110, 95)
        self.assertEqual(score, 30.0)  # Only price > EMA20 > EMA50
        self.assertNotIn("All EMAs aligned bullish", reasons)
    
    def test_calculate_volume_score(self):
        """Test volume score calculation"""
        # Test high volume
        self.assertEqual(self.scorer.calculate_volume_score(2.5), 100.0)
        
        # Test moderate volume
        self.assertEqual(self.scorer.calculate_volume_score(1.5), 80.0)
        self.assertEqual(self.scorer.calculate_volume_score(1.2), 60.0)
        
        # Test low volume
        self.assertEqual(self.scorer.calculate_volume_score(0.8), 20.0)
    
    def test_score_opportunity_buy(self):
        """Test scoring an opportunity that should generate a BUY signal"""
        data = {
            "symbol": "BTC/USDT",
            "timeframe": "15m",
            "close": 50000,
            "ema_20": 49000,
            "ema_50": 48000,
            "ema_200": 45000,
            "rsi_14": 60,
            "volume_ratio_20": 2.0,
            "spread_pct": 0.05
        }
        
        result = self.scorer.score_opportunity(data)
        
        # Should be a BUY signal with high score
        self.assertEqual(result.action, "BUY")
        self.assertGreater(result.total_score, 75.0)
        self.assertEqual(result.symbol, "BTC/USDT")
    
    def test_score_opportunity_skip(self):
        """Test scoring an opportunity that should generate a SKIP signal"""
        data = {
            "symbol": "SHIT/USDT",
            "timeframe": "15m",
            "close": 0.0001,
            "ema_20": 0.0002,
            "ema_50": 0.0003,
            "ema_200": 0.0004,
            "rsi_14": 85,
            "volume_ratio_20": 0.2,
            "spread_pct": 0.5
        }
        
        result = self.scorer.score_opportunity(data)
        
        # Should be a SKIP signal with low score
        self.assertEqual(result.action, "SKIP")
        self.assertLess(result.total_score, 60.0)
        self.assertEqual(result.symbol, "SHIT/USDT")

if __name__ == '__main__':
    unittest.main()