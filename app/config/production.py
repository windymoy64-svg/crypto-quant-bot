from __future__ import annotations

import atexit
import logging
import os
import platform
from dataclasses import dataclass
from pathlib import Path

from app.config.env import get_bool_env, get_exchange_credentials
from app.market.storage import DEFAULT_HISTORY_DB, SQLiteCandleStorage


BOT_VERSION = "1.0.0"
RUNTIME_DIRECTORIES = (Path("logs"), Path("data"), Path("configs"), Path("logs/backtests"))
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StartupInfo:
    python_version: str
    bot_version: str
    exchange: str
    dashboard_port: int
    mode: str
    sqlite_path: str

    def as_dict(self) -> dict[str, object]:
        return {
            "python_version": self.python_version,
            "bot_version": self.bot_version,
            "exchange": self.exchange,
            "dashboard_port": self.dashboard_port,
            "mode": self.mode,
            "sqlite_path": self.sqlite_path,
        }


def load_dotenv_file(path: str | Path = ".env") -> None:
    target = Path(path)
    if not target.exists():
        return
    for raw_line in target.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def required_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        raise RuntimeError(f"{name} must be set in .env or environment")
    return value.strip()


def ensure_runtime_directories() -> None:
    for directory in RUNTIME_DIRECTORIES:
        directory.mkdir(parents=True, exist_ok=True)


def validate_environment() -> None:
    ensure_runtime_directories()
    api_host = required_env("BOT_API_HOST")
    api_key = required_env("BOT_API_KEY")
    required_env("BOT_API_PORT")
    if api_host != "localhost" and not api_key:
        logger.warning("BOT_API_KEY is empty while BOT_API_HOST is not localhost")
    if not Path("configs").exists():
        logger.warning("configs directory is missing")


def runtime_mode() -> str:
    try:
        from app.settings.execution_preferences import load_execution_preferences
        stored = load_execution_preferences()
        if stored.mode in {"paper", "dry_run", "live"}:
            return stored.mode.replace("_", "-")
    except Exception:
        pass
    if get_bool_env("LIVE_TRADING_ENABLED", False):
        return "live-dry-run" if get_bool_env("LIVE_TRADING_DRY_RUN", True) else "live"
    if get_bool_env("PAPER_TRADING_ENABLED", True):
        return "paper"
    return "dry-run"


def startup_info() -> StartupInfo:
    credentials = get_exchange_credentials()
    exchange = credentials.exchange_id
    try:
        from app.settings.portfolio_preferences import load_portfolio_preferences
        exchange = load_portfolio_preferences().active_execution_exchange
    except Exception:
        pass
    return StartupInfo(
        python_version=platform.python_version(),
        bot_version=os.getenv("BOT_VERSION", BOT_VERSION),
        exchange=exchange,
        dashboard_port=int(required_env("BOT_API_PORT")),
        mode=runtime_mode(),
        sqlite_path=str(DEFAULT_HISTORY_DB),
    )


def log_startup_info() -> None:
    info = startup_info()
    logger.info("Production startup validation complete", extra={"startup": info.as_dict()})
    print(
        " | ".join(
            [
                f"Python {info.python_version}",
                f"Bot {info.bot_version}",
                f"Exchange {info.exchange}",
                f"Dashboard port {info.dashboard_port}",
                f"Mode {info.mode}",
                f"SQLite {info.sqlite_path}",
            ]
        ),
        flush=True,
    )


def sqlite_checkpoint() -> None:
    db_path = Path(DEFAULT_HISTORY_DB)
    if not db_path.exists():
        return
    try:
        SQLiteCandleStorage(db_path).checkpoint()
    except Exception:
        logger.exception("SQLite checkpoint failed during shutdown")


def production_startup() -> None:
    load_dotenv_file()
    validate_environment()
    log_startup_info()
    _bootstrap_futures_if_enabled()
    atexit.register(sqlite_checkpoint)


def _bootstrap_futures_if_enabled() -> None:
    """Best-effort hook: apply Binance futures config only for Binance."""

    try:
        from app.settings.portfolio_preferences import load_portfolio_preferences
        if load_portfolio_preferences().active_execution_exchange != "binance":
            return
    except Exception:
        pass

    try:
        from app.exchange.binance_futures.lifecycle import (
            bootstrap_futures_if_enabled,
        )
    except Exception:  # pragma: no cover - defensive import
        logger.debug("Futures lifecycle module unavailable", exc_info=True)
        return
    try:
        bootstrap_futures_if_enabled()
    except Exception:  # pragma: no cover - lifecycle already swallows errors
        logger.warning("Unexpected futures bootstrap failure", exc_info=True)


def production_shutdown() -> None:
    sqlite_checkpoint()
