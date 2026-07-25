import unittest
from datetime import datetime, timedelta
from app.data.data_integrity import DataIntegrityGate, DataIntegrityResult

class TestDataIntegrity(unittest.TestCase):
    
    def setUp(self):
        self.gate = DataIntegrityGate(max_freshness_seconds=300)
    
    def create_valid_candles(self, count=5, interval_seconds=900):
        """Create a list of valid OHLCV candles"""
        candles = []
        base_time = int(datetime.now().timestamp() * 1000) - (count * interval_seconds * 1000)
        
        for i in range(count):
            candles.append({
                "timestamp": base_time + (i * interval_seconds * 1000),
                "open": 100.0 + i,
                "high": 105.0 + i,
                "low": 95.0 + i,
                "close": 102.0 + i,
                "volume": 1000.0 + i * 10,
                "exchange": "binance",
                "is_synthetic": False
            })
        
        return candles
    
    def test_valid_data(self):
        """Test validation of valid OHLCV data"""
        candles = self.create_valid_candles()
        result = self.gate.validate_ohlcv(candles, "BTC/USDT", "15m")
        
        self.assertTrue(result.is_valid)
        self.assertFalse(result.is_synthetic)
        self.assertEqual(result.data_source, "binance")
        self.assertEqual(len(result.errors), 0)
    
    def test_synthetic_data(self):
        """Test rejection of synthetic data"""
        candles = self.create_valid_candles()
        candles[0]["is_synthetic"] = True
        
        result = self.gate.validate_ohlcv(candles, "BTC/USDT", "15m")
        
        self.assertFalse(result.is_valid)
        self.assertTrue(result.is_synthetic)
        self.assertIn("Synthetic data detected - reject", result.errors)
    
    def test_duplicate_candles(self):
        """Test detection of duplicate candles"""
        candles = self.create_valid_candles()
        # Create a duplicate timestamp
        candles.append(candles[0].copy())
        
        result = self.gate.validate_ohlcv(candles, "BTC/USDT", "15m")
        
        self.assertFalse(result.is_valid)
        self.assertIn("Duplicate candles detected", result.errors)
    
    def test_invalid_ohlc(self):
        """Test detection of invalid OHLC values"""
        candles = self.create_valid_candles()
        # Create invalid OHLC (high < low)
        candles[0]["high"] = 90.0
        candles[0]["low"] = 100.0
        
        result = self.gate.validate_ohlcv(candles, "BTC/USDT", "15m")
        
        self.assertFalse(result.is_valid)
        self.assertTrue(any("Invalid OHLC values" in error for error in result.errors))
    
    def test_negative_volume(self):
        """Test detection of negative volume"""
        candles = self.create_valid_candles()
        candles[0]["volume"] = -100.0
        
        result = self.gate.validate_ohlcv(candles, "BTC/USDT", "15m")
        
        self.assertFalse(result.is_valid)
        self.assertTrue(any("Negative volume" in error for error in result.errors))
    
    def test_stale_data(self):
        """Test detection of stale data"""
        candles = self.create_valid_candles()
        # Make the last candle very old
        candles[-1]["timestamp"] = int((datetime.now() - timedelta(hours=1)).timestamp() * 1000)
        
        result = self.gate.validate_ohlcv(candles, "BTC/USDT", "15m")
        
        self.assertFalse(result.is_valid)
        self.assertTrue(any("Data is stale" in error for error in result.errors))
    
    def test_empty_data(self):
        """Test handling of empty data"""
        result = self.gate.validate_ohlcv([], "BTC/USDT", "15m")
        
        self.assertFalse(result.is_valid)
        self.assertIn("No data provided", result.errors)

if __name__ == '__main__':
    unittest.main()