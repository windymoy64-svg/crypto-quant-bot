"""Dashboard endpoints for the USDⓈ-M Futures venue.

Reads / writes ``configs/futures.json`` and surfaces account state so the
operator can toggle the venue without hand-editing the file. Every write is
validated through :class:`FuturesConfig.from_dict` first, and the file is
saved atomically (tmp + rename) so a crash mid-write cannot leave a broken
config on disk.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from app.exchange.binance.auth import BinanceAuth
from app.exchange.binance_futures.account import FuturesAccountReader
from app.exchange.binance_futures.client import (
    FuturesHttpClient,
    FuturesHttpError,
)
from app.exchange.binance_futures.config import DEFAULT_CONFIG_PATH, FuturesConfig
from app.exchange.binance_futures.lifecycle import bootstrap_futures_if_enabled


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["futures"])


def _load_config_dict(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "enabled": False,
            "venue": "usdm_futures",
            "network": "testnet",
            "position_mode": "one_way",
            "multi_assets_margin": False,
            "margin_type": "ISOLATED",
            "default_leverage": 3,
            "symbols": {},
            "recv_window": 5000,
        }
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".futures-", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _credentials_configured() -> bool:
    try:
        return BinanceAuth().credentials().is_configured
    except Exception:  # pragma: no cover - defensive
        return False


def _summary(config: FuturesConfig, raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": config.enabled,
        "venue": config.venue,
        "network": config.network,
        "endpoint": config.endpoint.value,
        "position_mode": config.position_mode.value,
        "multi_assets_margin": config.multi_assets_margin,
        "margin_type": config.margin_type.value,
        "default_leverage": config.default_leverage,
        "recv_window": config.recv_window,
        "symbols": [
            {
                "symbol": entry.symbol,
                "leverage": entry.leverage,
                "margin_type": entry.margin_type.value,
            }
            for entry in config.symbols
        ],
        "credentials_configured": _credentials_configured(),
        "raw": raw,
    }


@router.get("/settings/futures")
def get_futures_settings(config_path: str | None = None) -> dict[str, Any]:
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    try:
        raw = _load_config_dict(path)
        config = FuturesConfig.from_dict(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to load futures config from %s", path)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _summary(config, raw)


@router.put("/settings/futures")
def update_futures_settings(payload: dict[str, Any]) -> dict[str, Any]:
    """Persist a new futures config after validating it.

    Body follows the same schema as ``configs/futures.json``.
    """

    try:
        config = FuturesConfig.from_dict(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Round-trip through a JSON-safe copy so we do not persist unexpected
    # keys the operator might have appended by mistake.
    sanitized = {
        "enabled": bool(payload.get("enabled", config.enabled)),
        "venue": config.venue,
        "network": config.network,
        "position_mode": config.position_mode.value,
        "multi_assets_margin": config.multi_assets_margin,
        "margin_type": config.margin_type.value,
        "default_leverage": config.default_leverage,
        "recv_window": config.recv_window,
        "symbols": {
            entry.symbol: {
                "leverage": entry.leverage,
                "margin_type": entry.margin_type.value,
            }
            for entry in config.symbols
        },
    }

    try:
        _atomic_write(DEFAULT_CONFIG_PATH, sanitized)
    except Exception as exc:
        logger.exception("Failed to write futures config")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return _summary(config, sanitized)


@router.post("/settings/futures/bootstrap")
def trigger_futures_bootstrap() -> dict[str, Any]:
    """Run the futures bootstrap on demand and return the report."""

    report = bootstrap_futures_if_enabled(config_path=DEFAULT_CONFIG_PATH)
    if report is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "bootstrap_skipped: futures config disabled, credentials missing, "
                "or config file invalid"
            ),
        )
    return {
        "skipped": report.skipped,
        "ok": report.ok,
        "position_mode": (
            {
                "mode": report.position_mode.mode.value,
                "unchanged": report.position_mode.unchanged,
            }
            if report.position_mode is not None
            else None
        ),
        "multi_assets_changed": report.multi_assets_changed,
        "margin_type_results": [
            {
                "symbol": r.symbol,
                "margin_type": r.margin_type.value,
                "unchanged": r.unchanged,
            }
            for r in report.margin_type_results
        ],
        "leverage_results": [
            {
                "symbol": r.symbol,
                "leverage": r.leverage,
                "unchanged": r.unchanged,
                "max_notional_value": r.max_notional_value,
            }
            for r in report.leverage_results
        ],
        "errors": list(report.errors),
    }


@router.get("/futures/account")
def get_futures_account() -> dict[str, Any]:
    """Return a read-only snapshot of the futures account."""

    try:
        config = FuturesConfig.load()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    creds = BinanceAuth().credentials()
    if not creds.is_configured:
        raise HTTPException(
            status_code=400,
            detail="binance_credentials_missing: configure via Settings first",
        )

    client = FuturesHttpClient(
        api_key=creds.api_key,
        api_secret=creds.api_secret,
        endpoint=config.endpoint,
        recv_window=config.recv_window,
    )
    reader = FuturesAccountReader(client)
    try:
        snapshot = reader.snapshot()
    except FuturesHttpError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"binance_error[{exc.code}]: {exc.message}",
        ) from exc

    return {
        "endpoint": config.endpoint.value,
        "network": config.network,
        "can_trade": snapshot.can_trade,
        "can_withdraw": snapshot.can_withdraw,
        "fee_tier": snapshot.fee_tier,
        "total_wallet_balance": snapshot.total_wallet_balance,
        "total_unrealized_profit": snapshot.total_unrealized_profit,
        "total_margin_balance": snapshot.total_margin_balance,
        "available_balance": snapshot.available_balance,
        "balances": [
            {
                "asset": b.asset,
                "wallet_balance": b.wallet_balance,
                "available_balance": b.available_balance,
                "cross_unrealized_pnl": b.cross_unrealized_pnl,
            }
            for b in snapshot.balances
            if b.wallet_balance != 0 or b.available_balance != 0
        ],
        "positions": [
            {
                "symbol": p.symbol,
                "position_side": p.position_side,
                "position_amount": p.position_amount,
                "entry_price": p.entry_price,
                "mark_price": p.mark_price,
                "unrealized_profit": p.unrealized_profit,
                "leverage": p.leverage,
                "liquidation_price": p.liquidation_price,
                "margin_type": p.margin_type,
            }
            for p in snapshot.positions
            if p.position_amount != 0
        ],
    }

