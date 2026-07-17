"""Startup wiring for the USDⓈ-M Futures venue.

Reads ``configs/futures.json`` and, when ``enabled=true`` with valid API
credentials, runs :func:`apply_futures_settings` to bring the exchange into
the configured state. All failures are best-effort: they log warnings but
never raise, so a mis-configured futures venue cannot bring the dashboard
process down.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.exchange.binance_futures.bootstrap import (
    FuturesBootstrapReport,
    apply_futures_settings,
)
from app.exchange.binance_futures.client import FuturesHttpClient
from app.exchange.binance_futures.config import DEFAULT_CONFIG_PATH, FuturesConfig


logger = logging.getLogger(__name__)


def bootstrap_futures_if_enabled(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
) -> FuturesBootstrapReport | None:
    """Load futures config and apply it. Never raises.

    Returns ``None`` when nothing was attempted (config missing / disabled /
    credentials unavailable). Returns the bootstrap report otherwise. When
    the report contains errors they are logged but the caller still gets the
    report so it can surface them in a status endpoint if desired.
    """

    try:
        config = FuturesConfig.load(config_path)
    except Exception:
        logger.warning("Failed to load futures config from %s", config_path, exc_info=True)
        return None

    if not config.enabled:
        logger.debug("Futures config disabled; skipping bootstrap")
        return None

    credentials = _load_credentials()
    if credentials is None:
        logger.warning(
            "Futures bootstrap skipped: no Binance API credentials configured. "
            "Set them via the Settings panel or BINANCE_API_KEY env vars."
        )
        return None

    try:
        client = FuturesHttpClient(
            api_key=credentials[0],
            api_secret=credentials[1],
            endpoint=config.endpoint,
            recv_window=config.recv_window,
        )
    except Exception:
        logger.warning("Failed to create futures HTTP client", exc_info=True)
        return None

    try:
        report = apply_futures_settings(config, client)
    except Exception:
        logger.warning("Futures bootstrap raised unexpectedly", exc_info=True)
        return None

    if not report.ok:
        logger.warning(
            "Futures bootstrap completed with %d error(s): %s",
            len(report.errors),
            "; ".join(report.errors),
        )
    else:
        logger.info(
            "Futures bootstrap OK: %d symbols, position_mode=%s, multi_assets=%s",
            len(report.leverage_results),
            report.position_mode.mode.value if report.position_mode else "unchanged",
            report.multi_assets_changed,
        )
    return report


def _load_credentials() -> tuple[str, str] | None:
    """Resolve Binance API credentials without raising."""

    try:
        from app.exchange.binance.auth import BinanceAuth
    except Exception:
        logger.debug("BinanceAuth not importable", exc_info=True)
        return None
    try:
        creds = BinanceAuth().credentials()
    except Exception:
        logger.debug("BinanceAuth.credentials() failed", exc_info=True)
        return None
    if not creds.is_configured:
        return None
    return creds.api_key, creds.api_secret
