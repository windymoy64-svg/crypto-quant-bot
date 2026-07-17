"""Idempotent bootstrap for USDⓈ-M Futures account state.

Runs at startup to bring the exchange side in sync with the ``FuturesConfig``:
1. Position mode (one-way vs hedge).
2. Multi-assets margin mode.
3. Per-symbol margin type (isolated/crossed).
4. Per-symbol initial leverage.

Every action is safe to re-run: the leverage manager already swallows the
"no need to change" error codes, and the applier collects results so callers
can log what changed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.exchange.binance_futures.client import FuturesHttpClient, FuturesHttpError
from app.exchange.binance_futures.config import FuturesConfig, FuturesSymbolConfig
from app.exchange.binance_futures.leverage import (
    FuturesLeverageManager,
    LeverageChangeResult,
    MarginType,
    MarginTypeChangeResult,
    PositionModeChangeResult,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FuturesBootstrapReport:
    skipped: bool
    position_mode: PositionModeChangeResult | None = None
    multi_assets_changed: bool | None = None
    margin_type_results: list[MarginTypeChangeResult] = field(default_factory=list)
    leverage_results: list[LeverageChangeResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _resolved_symbols(config: FuturesConfig) -> list[FuturesSymbolConfig]:
    if config.symbols:
        return list(config.symbols)
    return []


def apply_futures_settings(
    config: FuturesConfig,
    client: FuturesHttpClient,
) -> FuturesBootstrapReport:
    """Bring the account into the configured futures state.

    Returns a :class:`FuturesBootstrapReport` describing every change. When
    ``config.enabled`` is False the bootstrap is skipped without touching the
    exchange.
    """

    if not config.enabled:
        logger.info("Futures bootstrap skipped: config.enabled=False")
        return FuturesBootstrapReport(skipped=True)

    manager = FuturesLeverageManager(client)
    errors: list[str] = []

    try:
        position_mode = manager.set_position_mode(config.position_mode)
    except FuturesHttpError as exc:
        position_mode = None
        errors.append(f"position_mode: [{exc.code}] {exc.message}")

    multi_assets_changed: bool | None
    try:
        multi_assets_changed = manager.set_multi_assets_margin(
            config.multi_assets_margin
        )
    except FuturesHttpError as exc:
        multi_assets_changed = None
        errors.append(f"multi_assets_margin: [{exc.code}] {exc.message}")

    margin_results: list[MarginTypeChangeResult] = []
    leverage_results: list[LeverageChangeResult] = []

    for entry in _resolved_symbols(config):
        _apply_symbol(
            entry, manager, config.margin_type, config.default_leverage,
            margin_results, leverage_results, errors,
        )

    report = FuturesBootstrapReport(
        skipped=False,
        position_mode=position_mode,
        multi_assets_changed=multi_assets_changed,
        margin_type_results=margin_results,
        leverage_results=leverage_results,
        errors=errors,
    )
    logger.info(
        "Futures bootstrap complete: ok=%s errors=%d symbols=%d",
        report.ok,
        len(errors),
        len(config.symbols),
    )
    return report


def _apply_symbol(
    entry: FuturesSymbolConfig,
    manager: FuturesLeverageManager,
    default_margin_type: MarginType,
    default_leverage: int,
    margin_results: list[MarginTypeChangeResult],
    leverage_results: list[LeverageChangeResult],
    errors: list[str],
) -> None:
    margin_type = entry.margin_type or default_margin_type
    leverage = entry.leverage or default_leverage

    try:
        margin_results.append(manager.set_margin_type(entry.symbol, margin_type))
    except FuturesHttpError as exc:
        errors.append(f"{entry.symbol} margin_type: [{exc.code}] {exc.message}")

    try:
        leverage_results.append(manager.set_leverage(entry.symbol, leverage))
    except FuturesHttpError as exc:
        errors.append(f"{entry.symbol} leverage: [{exc.code}] {exc.message}")
