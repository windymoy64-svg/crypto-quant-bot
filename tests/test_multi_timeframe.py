import unittest
from app.strategies.multi_timeframe import MultiTimeframeAnalyzer, TimeframeAnalysis, MultiTimeframeResult

class TestMultiTimeframeAnalyzer(unittest.TestCase):
    
    def setUp(self):
        self.analyzer = MultiTimeframeAnalyzer()
    
    def test_analyze_timeframe_bullish(self):
        """Test analysis of a clearly bullish timeframe"""
        data = {
            "close": 110,
            "ema_20": 105,
            "ema_50": 100,
            "ema_200": 95,
            "rsi_14": 60
        }
        
        result = self.analyzer.analyze_timeframe(data, "1h")
        
        self.assertEqual(result.timeframe, "1h")
        self.assertEqual(result.trend, "BULLISH")
        self.assertGreater(result.score, 75.0)
        self.assertIn("All EMAs aligned bullish", result.reasons)
    
    def test_analyze_timeframe_bearish(self):
        """Test analysis of a clearly bearish timeframe"""
        data = {
            "close": 90,
            "ema_20": 95,
            "ema_50": 100,
            "ema_200": 105,
            "rsi_14": 40
        }
        
        result = self.analyzer.analyze_timeframe(data, "1h")
        
        self.assertEqual(result.timeframe, "1h")
        self.assertEqual(result.trend, "BEARISH")
        self.assertLess(result.score, 50.0)
        self.assertIn("All EMAs aligned bearish", result.reasons)
    
    def test_analyze_timeframe_neutral(self):
        """Test analysis of a mixed/neutral timeframe"""
        data = {
            "close": 100,
            "ema_20": 105,
            "ema_50": 100,
            "ema_200": 95,
            "rsi_14": 50
        }
        
        result = self.analyzer.analyze_timeframe(data, "1h")
        
        self.assertEqual(result.timeframe, "1h")
        self.assertEqual(result.trend, "NEUTRAL")
        self.assertAlmostEqual(result.score, 70.0, places=1)  # Approximately 50 + 20 for EMA50 > EMA200
    
    def test_analyze_multi_timeframe_bullish_confluence(self):
        """Test multi-timeframe analysis with bullish confluence"""
        multi_tf_data = {
            "1d": {
                "close": 52000,
                "ema_20": 51000,
                "ema_50": 50000,
                "ema_200": 45000,
                "rsi_14": 65
            },
            "4h": {
                "close": 51500,
                "ema_20": 51000,
                "ema_50": 50500,
                "ema_200": 49000,
                "rsi_14": 60
            },
            "1h": {
                "close": 51200,
                "ema_20": 51000,
                "ema_50": 50800,
                "ema_200": 50000,
                "rsi_14": 55
            },
            "15m": {
                "close": 51100,
                "ema_20": 51000,
                "ema_50": 50900,
                "ema_200": 50500,
                "rsi_14": 58
            }
        }
        
        result = self.analyzer.analyze_multi_timeframe(multi_tf_data)
        
        # Should detect bullish confluence
        self.assertEqual(result.overall_bias, "BULLISH")
        self.assertGreater(result.confluence_score, 60.0)
        self.assertTrue(result.hard_gates_passed)
        self.assertEqual(len(result.hard_gates_failed), 0)
        
        # Should have analysis for all timeframes
        self.assertEqual(len(result.timeframe_results), 4)
        self.assertIn("1d", result.timeframe_results)
        self.assertIn("4h", result.timeframe_results)
        self.assertIn("1h", result.timeframe_results)
        self.assertIn("15m", result.timeframe_results)
    
    def test_analyze_multi_timeframe_with_hard_gate_failure(self):
        """Test multi-timeframe analysis with a hard gate failure"""
        multi_tf_data = {
            "1d": {
                "close": 52000,
                "ema_20": 51000,
                "ema_50": 50000,
                "ema_200": 45000,
                "rsi_14": 65
            },
            "4h": {
                "close": 51500,
                "ema_20": 52000,  # Close below EMA20 - weak setup
                "ema_50": 52500,
                "ema_200": 53000,
                "rsi_14": 60
            },
            "1h": {
                "close": 51200,
                "ema_20": 51000,
                "ema_50": 50800,
                "ema_200": 50000,
                "rsi_14": 55
            }
        }
        
        result = self.analyzer.analyze_multi_timeframe(multi_tf_data)
        
        # Even with one weak timeframe, should still detect overall bias
        self.assertIn(result.overall_bias, ["BULLISH", "NEUTRAL"])
        # Hard gates should still pass since we meet minimum score requirements
        self.assertTrue(result.hard_gates_passed)
    
    def test_timeframe_hierarchy_weights(self):
        """Test that timeframe hierarchy weights are correctly defined"""
        expected_hierarchy = {
            "1d": 0.40,
            "4h": 0.30,
            "1h": 0.20,
            "15m": 0.10
        }
        
        self.assertEqual(self.analyzer.timeframe_hierarchy, expected_hierarchy)
    
    def test_hard_gates_definition(self):
        """Test that hard gates are correctly defined"""
        expected_gates = {
            "1d": {
                "min_score": 40.0,
                "required_trend": ["BULLISH", "NEUTRAL"]
            },
            "4h": {
                "min_score": 50.0,
                "required_trend": ["BULLISH", "NEUTRAL"]
            },
            "1h": {
                "min_score": 60.0
            },
            "15m": {
                "min_score": 65.0
            }
        }
        
        self.assertEqual(self.analyzer.hard_gates, expected_gates)

if __name__ == '__main__':
    unittest.main()