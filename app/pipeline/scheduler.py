from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime
from app.market.exchange_adapter import ExchangeAdapter
from app.data.database import Database
from app.scoring.scorer import ScoringEngine
from app.risk.risk_manager import RiskManager
from app.alerts.telegram_alerts import TelegramAlerts
from typing import List
import asyncio

class PipelineScheduler:
    """Manages scheduled scanning and processing of market data"""
    
    def __init__(self, exchange_adapter: ExchangeAdapter, database: Database, 
                 scorer: ScoringEngine, risk_manager: RiskManager, 
                 telegram_alerts: TelegramAlerts):
        self.scheduler = AsyncIOScheduler()
        self.exchange_adapter = exchange_adapter
        self.database = database
        self.scorer = scorer
        self.risk_manager = risk_manager
        self.telegram_alerts = telegram_alerts
        
    async def collect_market_data(self):
        """Collect market data from exchange and store in database"""
        symbols = await self.exchange_adapter.get_market_universe()
        
        # Filter for USDT pairs and major coins
        usdt_symbols = [s for s in symbols if s.endswith('/USDT') and len(s.split('/')[0]) <= 10]
        
        for symbol in usdt_symbols[:50]:  # Limit to top 50 for performance
            for timeframe in ['15m', '1h', '4h', '1d']:
                try:
                    ohlcv_data = await self.exchange_adapter.get_ohlcv(symbol, timeframe, limit=200)
                    
                    # Convert to database format
                    db_records = []
                    for candle in ohlcv_data:
                        db_records.append({
                            'symbol': symbol,
                            'timeframe': timeframe,
                            'timestamp': candle['timestamp'],
                            'open': candle['open'],
                            'high': candle['high'],
    
    async def run_scan(self):
        """Run the main scanning process"""
        # Get latest data for all symbols/timeframes
        symbols = await self.exchange_adapter.get_market_universe()
        usdt_symbols = [s for s in symbols if s.endswith('/USDT') and len(s.split('/')[0]) <= 10][:20]  # Limit for performance
        
        for symbol in usdt_symbols:
            # Get multi-timeframe data
            multi_tf_data = {}
            for timeframe in ['1d', '4h', '1h', '15m']:
                try:
                    ohlcv = self.database.get_ohlcv(symbol, timeframe, limit=200)
                    if ohlcv:
                        # Convert to feature dictionary
                        latest_candle = ohlcv[0]  # Most recent
                        multi_tf_data[timeframe] = {
                            'symbol': symbol,
                            'timeframe': timeframe,
                            'close': latest_candle.close,
                            'high': latest_candle.high,
                            'low': latest_candle.low,
                            'open': latest_candle.open,
                            'volume': latest_candle.volume,
                            # Calculate indicators here or pre-calculate
                            'ema_20': 0,  # Placeholder - would be calculated
                            'ema_50': 0,
                            'ema_200': 0,
                            'rsi_14': 0,
                            'volume_ratio_20': 0
                        }
                except Exception as e:
                    print(f"Error getting data for {symbol} {timeframe}: {e}")
            
            if multi_tf_data:
                # Perform multi-timeframe analysis
                from app.strategies.multi_timeframe import MultiTimeframeAnalyzer
                analyzer = MultiTimeframeAnalyzer()
                
                try:
                    result = analyzer.analyze_multi_timeframe(multi_tf_data)
                    
                    # If hard gates passed, score the opportunity
                    if result.hard_gates_passed:
                        # Score using the main scorer
                        feature_dict = self._prepare_feature_dict(multi_tf_data)
                        score_result = self.scorer.score_opportunity(feature_dict)
                        
                        # Apply risk check
                        risk_result = self.risk_manager.check_opportunity(
                            feature_dict, score_result.confluence_score
                        )
                        
                        # If risk check passes and action is BUY/WATCH, send alert
                        if risk_result.passed and score_result.action in ['BUY', 'WATCH']:
                            # Format and send alert
                            self.telegram_alerts.send_alert(score_result)
                            
                except Exception as e:
                    print(f"Error analyzing {symbol}: {e}")
    
    def _prepare_feature_dict(self, multi_tf_data: dict) -> dict:
        """Prepare feature dictionary for scoring"""
        # Take the highest timeframe data as primary
        primary_tf = '15m'  # Default
        if '15m' in multi_tf_data:
            primary_tf = '15m'
        elif '1h' in multi_tf_data:
            primary_tf = '1h'
        elif '4h' in multi_tf_data:
            primary_tf = '4h'
        elif '1d' in multi_tf_data:
            primary_tf = '1d'
        
        # Return the primary timeframe data with defaults for missing values
        data = multi_tf_data.get(primary_tf, {})
        return {
            'symbol': data.get('symbol', 'UNKNOWN'),
            'timeframe': data.get('timeframe', '15m'),
            'close': data.get('close', 0),
            'high': data.get('high', 0),
            'low': data.get('low', 0),
            'open': data.get('open', 0),
            'volume': data.get('volume', 0),
            'ema_20': data.get('ema_20', 0),
            'ema_50': data.get('ema_50', 0),
            'ema_200': data.get('ema_200', 0),
            'rsi_14': data.get('rsi_14', 50),
            'volume_ratio_20': data.get('volume_ratio_20', 1.0),
            'spread_pct': data.get('spread_pct', 0.01),
            'data_freshness_seconds': 60,  # Placeholder
            'stop_loss': data.get('close', 0) * 0.95,  # Placeholder
            'risk_reward_ratio': 2.0  # Placeholder
        }
    
    def start(self):
        """Start the scheduler"""
        # Schedule data collection every 5 minutes
        self.scheduler.add_job(
            self.collect_market_data,
            CronTrigger(minute='*/5'),
            id='collect_data',
            name='Collect market data',
            replace_existing=True
        )
        
        # Schedule scanning every 15 minutes
        self.scheduler.add_job(
            self.run_scan,
            CronTrigger(minute='*/15'),
            id='run_scan',
            name='Run market scan',
            replace_existing=True
        )
        
        self.scheduler.start()
        print("Pipeline scheduler started")
    
    def shutdown(self):
        """Shutdown the scheduler"""
        self.scheduler.shutdown()
                            'low': candle['low'],
                            'close': candle['close'],
                            'volume': candle['volume']
                        })
                    
                    # Store in database
                    self.database.insert_ohlcv(db_records)
                except Exception as e:
                    print(f"Error collecting data for {symbol} {timeframe}: {e}")