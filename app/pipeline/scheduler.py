from __future__ import annotations

from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.alerts.telegram_alerts import TelegramAlerts
from app.data.database import Database
from app.market.exchange_adapter import ExchangeAdapter
from app.risk.risk_manager import RiskManager
from app.scoring.scorer import ScoringEngine


class PipelineScheduler:
    """Manage bounded scheduled collection and market scans."""

    def __init__(self, exchange_adapter: ExchangeAdapter, database: Database,
                 scorer: ScoringEngine, risk_manager: RiskManager,
                 telegram_alerts: TelegramAlerts) -> None:
        self.scheduler = AsyncIOScheduler()
        self.exchange_adapter = exchange_adapter
        self.database = database
        self.scorer = scorer
        self.risk_manager = risk_manager
        self.telegram_alerts = telegram_alerts

    async def collect_market_data(self) -> None:
        """Collect a bounded universe and persist each candle batch immediately."""
        symbols = await self.exchange_adapter.get_market_universe()
        usdt_symbols = [s for s in symbols if s.endswith("/USDT")
                        and len(s.split("/")[0]) <= 10][:50]
        for symbol in usdt_symbols:
            for timeframe in ("15m", "1h", "4h", "1d"):
                try:
                    candles = await self.exchange_adapter.get_ohlcv(
                        symbol, timeframe, limit=200)
                    records = [{
                        "symbol": symbol, "timeframe": timeframe,
                        "timestamp": candle["timestamp"], "open": candle["open"],
                        "high": candle["high"], "low": candle["low"],
                        "close": candle["close"], "volume": candle["volume"],
                    } for candle in candles]
                    if records:
                        self.database.insert_ohlcv(records)
                except Exception as exc:  # noqa: BLE001
                    print(f"Error collecting data for {symbol} {timeframe}: {exc}")

    async def run_scan(self) -> None:
        """Analyze the latest bounded multi-timeframe data."""
        symbols = await self.exchange_adapter.get_market_universe()
        usdt_symbols = [s for s in symbols if s.endswith("/USDT")
                        and len(s.split("/")[0]) <= 10][:20]
        for symbol in usdt_symbols:
            multi_tf_data: dict[str, dict[str, Any]] = {}
            for timeframe in ("1d", "4h", "1h", "15m"):
                try:
                    rows = self.database.get_ohlcv(symbol, timeframe, limit=200)
                    if rows:
                        latest = rows[0]
                        multi_tf_data[timeframe] = {
                            "symbol": symbol, "timeframe": timeframe,
                            "close": latest.close, "high": latest.high,
                            "low": latest.low, "open": latest.open,
                            "volume": latest.volume, "ema_20": 0,
                            "ema_50": 0, "ema_200": 0, "rsi_14": 0,
                            "volume_ratio_20": 0,
                        }
                except Exception as exc:  # noqa: BLE001
                    print(f"Error loading data for {symbol} {timeframe}: {exc}")
            if not multi_tf_data:
                continue
            try:
                features = self._prepare_feature_dict(multi_tf_data)
                score_result = self.scorer.score_opportunity(features)
                risk_result = self.risk_manager.check_opportunity(
                    features, score_result.confluence_score)
                if risk_result.passed and score_result.action in {"BUY", "WATCH"}:
                    self.telegram_alerts.send_alert(score_result)
            except Exception as exc:  # noqa: BLE001
                print(f"Error analyzing {symbol}: {exc}")

    def _prepare_feature_dict(self, multi_tf_data: dict[str, dict[str, Any]]) -> dict[str, Any]:
        primary_tf = next((tf for tf in ("15m", "1h", "4h", "1d")
                           if tf in multi_tf_data), "15m")
        data = multi_tf_data.get(primary_tf, {})
        close = float(data.get("close", 0) or 0)
        return {
            "symbol": data.get("symbol", "UNKNOWN"),
            "timeframe": data.get("timeframe", primary_tf),
            "close": close, "high": data.get("high", 0),
            "low": data.get("low", 0), "open": data.get("open", 0),
            "volume": data.get("volume", 0), "ema_20": data.get("ema_20", 0),
            "ema_50": data.get("ema_50", 0), "ema_200": data.get("ema_200", 0),
            "rsi_14": data.get("rsi_14", 50),
            "volume_ratio_20": data.get("volume_ratio_20", 1.0),
            "spread_pct": data.get("spread_pct", 0.01),
            "data_freshness_seconds": 60, "stop_loss": close * 0.95,
            "risk_reward_ratio": 2.0,
        }

    def start(self) -> None:
        self.scheduler.add_job(self.collect_market_data, CronTrigger(minute="*/5"),
                               id="collect_data", name="Collect market data",
                               replace_existing=True, max_instances=1, coalesce=True)
        self.scheduler.add_job(self.run_scan, CronTrigger(minute="*/15"),
                               id="run_scan", name="Run market scan",
                               replace_existing=True, max_instances=1, coalesce=True)
        self.scheduler.start()
        print("Pipeline scheduler started")

    def shutdown(self) -> None:
        self.scheduler.shutdown()