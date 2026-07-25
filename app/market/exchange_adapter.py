import ccxt
from typing import List, Dict
from config.exchange_config import ExchangeConfig

class ExchangeAdapter:
    """Handles interactions with the exchange API"""
    
    def __init__(self, config: ExchangeConfig):
        self.exchange = ccxt.binance({
            'apiKey': config.api_key,
            'secret': config.secret_key,
            'enableRateLimit': True
        })
    
    async def get_market_universe(self) -> List[str]:
        """Get list of tradable pairs"""
        markets = await self.exchange.fetch_markets()
        return [market['symbol'] for market in markets if market['active']]
    
    async def get_ohlcv(self, symbol: str, timeframe: str, limit: int = 100) -> List[Dict]:
        """Get OHLCV data for a symbol"""
        ohlcv = await self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        return [{
            'timestamp': candle[0],
            'open': candle[1],
            'high': candle[2],
            'low': candle[3],
            'close': candle[4],
            'volume': candle[5]
        } for candle in ohlcv]
    
    async def get_order_book(self, symbol: str) -> Dict:
        """Get order book for a symbol"""
        order_book = await self.exchange.fetch_order_book(symbol)
        return {
            'asks': order_book['asks'],
            'bids': order_book['bids']
        }
    
    async def get_ticker(self, symbol: str) -> Dict:
        """Get ticker information for a symbol"""
        ticker = await self.exchange.fetch_ticker(symbol)
        return ticker