"""Persisted dashboard preferences for a multi-exchange portfolio.

These preferences intentionally do not enable trading.  They only define the
read-only portfolio view and the single exchange that the execution runtime is
allowed to use when execution is explicitly enabled elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.settings.exchange_credentials import DEFAULT_EXCHANGE, SUPPORTED_EXCHANGES
from app.settings.store import SecretsStore, get_secrets_store


PORTFOLIO_MODE_SINGLE = "single"
PORTFOLIO_MODE_MULTI = "multi"
PORTFOLIO_MODES = (PORTFOLIO_MODE_SINGLE, PORTFOLIO_MODE_MULTI)
_ACTIVE_EXCHANGE_KEY = "portfolio.active_execution_exchange"
_VIEW_MODE_KEY = "portfolio.view_mode"


@dataclass(frozen=True)
class PortfolioPreferences:
    active_execution_exchange: str = DEFAULT_EXCHANGE
    view_mode: str = PORTFOLIO_MODE_SINGLE

    @property
    def multi_exchange_enabled(self) -> bool:
        return self.view_mode == PORTFOLIO_MODE_MULTI


def load_portfolio_preferences(
    store: SecretsStore | None = None,
) -> PortfolioPreferences:
    store = store or get_secrets_store()
    return PortfolioPreferences(
        active_execution_exchange=_normalize_exchange(store.get(_ACTIVE_EXCHANGE_KEY)),
        view_mode=_normalize_view_mode(store.get(_VIEW_MODE_KEY)),
    )


def save_portfolio_preferences(
    *,
    active_execution_exchange: str,
    view_mode: str,
    store: SecretsStore | None = None,
) -> PortfolioPreferences:
    store = store or get_secrets_store()
    exchange = _normalize_exchange(active_execution_exchange)
    mode = _normalize_view_mode(view_mode)
    store.set(_ACTIVE_EXCHANGE_KEY, exchange)
    store.set(_VIEW_MODE_KEY, mode)
    return PortfolioPreferences(
        active_execution_exchange=exchange,
        view_mode=mode,
    )


def _normalize_exchange(value: str | None) -> str:
    exchange = (value or DEFAULT_EXCHANGE).strip().lower()
    if exchange not in SUPPORTED_EXCHANGES:
        raise ValueError(
            f"Unsupported exchange {exchange!r}; expected one of {SUPPORTED_EXCHANGES}"
        )
    return exchange


def _normalize_view_mode(value: str | None) -> str:
    mode = (value or PORTFOLIO_MODE_SINGLE).strip().lower()
    if mode not in PORTFOLIO_MODES:
        raise ValueError(
            f"Unsupported portfolio view mode {mode!r}; expected one of {PORTFOLIO_MODES}"
        )
    return mode