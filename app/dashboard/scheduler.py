"""Daily reset scheduler untuk dashboard data.

Reset terjadi setiap 07:00 WIB (00:00 UTC) untuk clear history trades
dan analytics, tapi preserve balance dan open positions.
"""
import logging
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger


logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def reset_daily_data() -> None:
    """Reset order history dan analytics di awal sesi WIB (07:00 WIB = 00:00 UTC).
    
    Yang di-reset:
    - logs/paper_trades.jsonl (history trades)
    - logs/latest_signals.json (sinyal lama, kecuali tracked)
    
    Yang TIDAK di-reset:
    - logs/paper_state.json (balance + open positions)
    - logs/portfolio_state.json (live positions)
    """
    logger.info("Daily reset triggered at 07:00 WIB (00:00 UTC)")
    
    # Reset paper trades history
    trades_file = Path("logs/paper_trades.jsonl")
    if trades_file.exists():
        try:
            # Backup before truncate
            backup = Path(f"logs/paper_trades_backup_{trades_file.stat().st_mtime_ns}.jsonl")
            trades_file.rename(backup)
            trades_file.touch()
            logger.info(f"Reset paper trades: {trades_file} (backup: {backup.name})")
        except Exception as e:
            logger.exception(f"Failed to reset paper trades: {e}")
    
    # Reset latest signals (preserve structure tapi clear arrays)
    signals_file = Path("logs/latest_signals.json")
    if signals_file.exists():
        try:
            import json
            # Preserve struktur tapi clear signals arrays
            reset_data = {
                "signals": [],
                "short_signals": [],
                "tracked_signals": [],
                "symbols": [],
                "configured_symbols": [],
                "count": 0,
                "timestamp": "",
            }
            signals_file.write_text(json.dumps(reset_data, indent=2))
            logger.info(f"Reset signals: {signals_file}")
        except Exception as e:
            logger.exception(f"Failed to reset signals: {e}")
    
    logger.info("Daily reset completed successfully")


def start_scheduler() -> None:
    """Start background scheduler dengan daily reset job jam 00:00 UTC (07:00 WIB)."""
    global _scheduler
    
    if _scheduler is not None:
        logger.warning("Scheduler already running, skipping start")
        return
    
    _scheduler = BackgroundScheduler(timezone="UTC")
    
    # Job daily reset jam 00:00 UTC = 07:00 WIB
    # Karena WIB = UTC+7, maka 07:00 WIB = 00:00 UTC
    trigger = CronTrigger(hour=0, minute=0, second=0, timezone="UTC")
    _scheduler.add_job(
        reset_daily_data,
        trigger=trigger,
        id="daily_reset_wib",
        name="Daily Reset 07:00 WIB",
        replace_existing=True,
    )
    
    _scheduler.start()
    logger.info("Scheduler started with daily reset job at 00:00 UTC (07:00 WIB)")


def shutdown_scheduler() -> None:
    """Shutdown scheduler gracefully."""
    global _scheduler
    
    if _scheduler is None:
        return
    
    try:
        _scheduler.shutdown(wait=True)
        logger.info("Scheduler shutdown completed")
    except Exception as e:
        logger.exception(f"Scheduler shutdown failed: {e}")
    finally:
        _scheduler = None
