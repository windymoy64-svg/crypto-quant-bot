from __future__ import annotations

import os
import shutil
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.market.storage import DEFAULT_HISTORY_DB


class SystemHealthMonitor:
    def __init__(self) -> None:
        self.started_at = time.time()

    def snapshot(self) -> dict[str, Any]:
        started = time.perf_counter()
        disk = shutil.disk_usage(Path.cwd())
        return {
            "timestamp": datetime.now(UTC).isoformat(),
            "uptime_seconds": round(time.time() - self.started_at, 3),
            "cpu": self._cpu(),
            "ram": self._ram(),
            "disk": {"total": disk.total, "used": disk.used, "free": disk.free, "percent": round((disk.used / disk.total) * 100, 2) if disk.total else 0.0},
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            "api_status": "ok",
            "websocket_status": "ready",
            "exchange_status": "configured" if os.getenv("BINANCE_API_KEY") or os.getenv("EXCHANGE_API_KEY") else "not_configured",
            "binance_connectivity": self._binance_connectivity(),
            "sqlite": self._sqlite(),
            "process": {"pid": os.getpid()},
        }

    def _cpu(self) -> dict[str, Any]:
        return {"process_time_seconds": round(time.process_time(), 3), "source": "stdlib"}

    def _ram(self) -> dict[str, Any]:
        if hasattr(os, "sysconf"):
            try:
                total = int(os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE"))
                return {"total": total, "process_rss": None, "source": "sysconf"}
            except (ValueError, OSError, AttributeError):
                pass
        return {"total": None, "process_rss": None, "source": "unavailable"}

    def _sqlite(self) -> dict[str, Any]:
        path = Path(DEFAULT_HISTORY_DB)
        if not path.exists():
            return {"status": "missing", "path": str(path), "wal": False}
        try:
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5) as connection:
                journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0])
            return {"status": "ok", "path": str(path), "journal_mode": journal_mode, "wal": journal_mode.lower() == "wal"}
        except sqlite3.Error as exc:
            return {"status": "error", "path": str(path), "error": str(exc), "wal": False}

    def _binance_connectivity(self) -> dict[str, Any]:
        configured = bool(os.getenv("BINANCE_API_KEY") or os.getenv("EXCHANGE_API_KEY"))
        return {"configured": configured, "status": "not_checked" if configured else "not_configured"}


system_health_monitor = SystemHealthMonitor()
