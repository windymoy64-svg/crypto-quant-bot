from typing import List, Dict, Tuple
import math
from app.indicators.technical import calculate_ema, calculate_rsi, calculate_atr, calculate_macd, calculate_bollinger_bands

class IndicatorCalculator:
    """Calculates technical indicators for trading signals"""
    
    @staticmethod
    def calculate_all_indicators(candles: List[Dict], symbol: str, timeframe: str) -> Dict:
        """Calculate all relevant indicators for a given symbol and timeframe"""
        if not candles or len(candles) < 20:
            return {}
        
        # Extract price data
        closes = [candle['close'] for candle in candles]
        highs = [candle['high'] for candle in candles]
        lows = [candle['low'] for candle in candles]
        volumes = [candle['volume'] for candle in candles]
        
        # Calculate indicators
        indicators = {}
        
        # EMA indicators
        ema_20 = calculate_ema(closes, 20)
        ema_50 = calculate_ema(closes, 50)
        ema_200 = calculate_ema(closes, 200)
        indicators['ema_20'] = ema_20
        indicators['ema_50'] = ema_50
        indicators['ema_200'] = ema_200
        
        # RSI
        rsi_14 = calculate_rsi(closes, 14)
        indicators['rsi_14'] = rsi_14
        
        # ATR
        atr_14 = calculate_atr(highs, lows, closes, 14)
        indicators['atr_14'] = atr_14
        
        # MACD
        macd = calculate_macd(closes, 12, 26, 9)
        indicators['macd_line'] = macd['macd_line']
        indicators['signal_line'] = macd['signal_line']
        indicators['histogram'] = macd['histogram']
        
        # Bollinger Bands
        bb = calculate_bollinger_bands(closes, 20, 2.0)
        indicators['bb_upper'] = bb['upper_band']
        indicators['bb_middle'] = bb['middle_band']
        indicators['bb_lower'] = bb['lower_band']
        indicators['bb_width'] = bb['bandwidth']
        
        # Volume indicators
        if len(volumes) >= 20:
            volume_avg = sum(volumes[-20:]) / 20
            volume_ratio = volumes[-1] / volume_avg if volume_avg > 0 else 1.0
            indicators['volume_ratio_20'] = volume_ratio
        
        # Price vs EMA distance
        if ema_20 > 0:
            price_ema_distance = abs(closes[-1] - ema_20) / ema_20 * 100
            indicators['price_ema_distance'] = price_ema_distance
        
        # Add timestamp of last candle
        indicators['timestamp'] = candles[-1]['timestamp']
        indicators['symbol'] = symbol
        indicators['timeframe'] = timeframe
        
        return indicators

    @staticmethod
    def calculate_momentum_indicators(candles: List[Dict]) -> Dict:
        """Calculate momentum-related indicators"""
        if len(candles) < 14:
            return {}
        
        closes = [candle['close'] for candle in candles]
        
        # Momentum
        momentum = closes[-1] - closes[-14] if len(closes) >= 14 else 0.0
        momentum_14 = momentum
        
        # Rate of Change
        roc = ((closes[-1] - closes[-14]) / closes[-14] * 100) if closes[-14] != 0 else 0.0
        
        # Relative Strength Index
        rsi = calculate_rsi(closes, 14)
        
        return {
            'momentum_14': momentum_14,
            'roc_14': roc,
            'rsi_14': rsi
        }

    @staticmethod
    def calculate_volatility_indicators(candles: List[Dict]) -> Dict:
        """Calculate volatility-related indicators"""
        if len(candles) < 14:
            return {}
        
        highs = [candle['high'] for candle in candles]
        lows = [candle['low'] for candle in candles]
        closes = [candle['close'] for candle in candles]
        
        # ATR
        atr = calculate_atr(highs, lows, closes, 14)
        
        # Historical volatility
        volatility = calculate_atr(highs, lows, closes, 14)  # Simplified
        
        # Bollinger Band width
        bb = calculate_bollinger_bands(closes, 20, 2.0)
        bb_width = bb['bandwidth']
        
        return {
            'atr_14': atr,
            'volatility': volatility,
            'bb_width': bb_width
        }