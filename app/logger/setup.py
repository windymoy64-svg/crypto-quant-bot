from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "process": record.process,
            "thread": record.threadName,
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True)


class MaxLevelFilter(logging.Filter):
    def __init__(self, max_level: int) -> None:
        super().__init__()
        self.max_level = max_level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno <= self.max_level


def _daily_handler(path: Path, level: int) -> TimedRotatingFileHandler:
    handler = TimedRotatingFileHandler(path, when="midnight", backupCount=14, encoding="utf-8", utc=True)
    handler.setLevel(level)
    handler.setFormatter(JsonFormatter())
    return handler


def setup_production_logging(log_dir: str | Path = "logs") -> None:
    target = Path(log_dir)
    target.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(JsonFormatter())

    app_handler = _daily_handler(target / "bot.log", logging.INFO)
    warning_handler = _daily_handler(target / "warning.log", logging.WARNING)
    warning_handler.addFilter(MaxLevelFilter(logging.WARNING))
    error_handler = _daily_handler(target / "error.log", logging.ERROR)

    root.addHandler(console)
    root.addHandler(app_handler)
    root.addHandler(warning_handler)
    root.addHandler(error_handler)
