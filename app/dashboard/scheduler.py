"""Daily reset scheduler untuk dashboard data.

Reset terjadi setiap 07:00 WIB (00:00 UTC) untuk clear history trades
dan analytics, tapi preserve balance dan open positions.
"""
import gzip
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger


logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None

# Batas berapa hari arsip .jsonl.gz dipertahankan supaya folder logs
# tidak membengkak tanpa batas.
ARCHIVE_RETENTION_DAYS = 30


def _archive_and_truncate(source: Path, archive_dir: Path, stem: str) -> None:
    """Rename file ke arsip .jsonl.gz lalu buat ulang file kosong.

    Aman untuk file yang ditulis dengan mode ``"a"`` per siklus karena
    handle baru selalu dibuka ulang; tidak ada file descriptor stale.
    """

    archive_dir.mkdir(parents=True, exist_ok=True)
    date_tag = datetime.now(tz=UTC).strftime("%Y%m%d")
    archive_path = archive_dir / f"{stem}_{date_tag}.jsonl.gz"

    # Jika ada arsip dengan nama sama (mis. daily reset dijalankan manual),
    # tambahkan suffix waktu untuk menghindari overwrite.
    if archive_path.exists():
        archive_path = archive_dir / (
            f"{stem}_{date_tag}_{datetime.now(tz=UTC).strftime('%H%M%S')}.jsonl.gz"
        )

    with source.open("rb") as raw, gzip.open(archive_path, "wb") as gz:
        shutil.copyfileobj(raw, gz)

    # Truncate in place agar file descriptor apapun yang mungkin dibuka
    # writer lain tetap valid; lebih aman daripada rename+touch race.
    with source.open("w", encoding="utf-8"):
        pass

    logger.info(
        "Archived %s to %s (%s bytes)",
        source,
        archive_path.name,
        archive_path.stat().st_size,
    )


def _prune_old_archives(archive_dir: Path, retention_days: int) -> None:
    if not archive_dir.exists():
        return
    cutoff = datetime.now(tz=UTC).timestamp() - retention_days * 86400
    for entry in archive_dir.glob("*.jsonl.gz"):
        try:
            if entry.stat().st_mtime < cutoff:
                entry.unlink()
                logger.info("Pruned old archive: %s", entry.name)
        except OSError:
            logger.exception("Failed to prune archive %s", entry)


def reset_daily_data() -> None:
    """Reset order history dan analytics di awal sesi WIB (07:00 WIB = 00:00 UTC).

    Yang di-reset (dengan arsip terkompresi):
    - logs/paper_trades.jsonl (history trades)
    - logs/signals.jsonl (riwayat scan realtime)
    - logs/latest_signals.json (sinyal lama, kecuali tracked)

    Yang TIDAK di-reset:
    - logs/paper_state.json (balance + open positions)
    - logs/portfolio_state.json (live positions)
    """
    logger.info("Daily reset triggered at 07:00 WIB (00:00 UTC)")

    archive_dir = Path("logs/archive")

    # Reset paper trades history (archive .gz)
    trades_file = Path("logs/paper_trades.jsonl")
    if trades_file.exists() and trades_file.stat().st_size > 0:
        try:
            _archive_and_truncate(trades_file, archive_dir, "paper_trades")
        except Exception:
            logger.exception("Failed to reset paper trades")

    # Reset signals history (archive .gz)
    history_file = Path("logs/signals.jsonl")
    if history_file.exists() and history_file.stat().st_size > 0:
        try:
            _archive_and_truncate(history_file, archive_dir, "signals")
        except Exception:
            logger.exception("Failed to reset signals history")

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

    # Housekeeping: hapus arsip lama supaya folder logs tidak membengkak
    _prune_old_archives(archive_dir, ARCHIVE_RETENTION_DAYS)

    logger.info("Daily reset completed successfully")


def start_scheduler() -> None:
    """Start background scheduler dengan daily reset job jam 00:00 UTC (07:00 WIB)."""
    global _scheduler

    try:
        if _scheduler is not None:
            logger.warning("Scheduler already running, skipping start")
            return

        logger.info("Starting daily reset scheduler...")
        _scheduler = BackgroundScheduler(timezone="UTC")

        trigger = CronTrigger(hour=0, minute=0, second=0, timezone="UTC")
        _scheduler.add_job(
            reset_daily_data,
            trigger=trigger,
            id="daily_reset_wib",
            name="Daily Reset 07:00 WIB",
            replace_existing=True,
        )

        _scheduler.start()
        logger.info("Scheduler started: daily reset at 00:00 UTC (07:00 WIB)")
    except Exception:
        logger.exception("Scheduler start failed")
        _scheduler = None


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
