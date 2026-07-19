"""Persisted execution mode with fail-closed live confirmation."""

from __future__ import annotations

from dataclasses import dataclass

from app.settings.exchange_credentials import SUPPORTED_EXCHANGES
from app.settings.store import SecretsStore, get_secrets_store


EXECUTION_MODES = ("paper", "dry_run", "live")
LIVE_CONFIRMATION = "ENABLE LIVE TRADING"
_MODE_KEY = "execution.mode"
_CONFIRMED_KEY = "execution.live_confirmed"


@dataclass(frozen=True)
class ExecutionPreferences:
    mode: str = "paper"
    live_confirmed: bool = False

    @property
    def network_enabled(self) -> bool:
        return self.mode == "live" and self.live_confirmed


def load_execution_preferences(store: SecretsStore | None = None) -> ExecutionPreferences:
    store = store or get_secrets_store()
    mode = (store.get(_MODE_KEY) or "paper").strip().lower()
    if mode not in EXECUTION_MODES:
        mode = "paper"
    confirmed = (store.get(_CONFIRMED_KEY) or "false").lower() == "true"
    return ExecutionPreferences(mode=mode, live_confirmed=confirmed and mode == "live")


def save_execution_preferences(
    *, mode: str, confirmation: str = "", store: SecretsStore | None = None,
) -> ExecutionPreferences:
    store = store or get_secrets_store()
    normalized = mode.strip().lower()
    if normalized not in EXECUTION_MODES:
        raise ValueError(f"mode must be one of {EXECUTION_MODES}")
    confirmed = normalized == "live" and confirmation.strip() == LIVE_CONFIRMATION
    if normalized == "live" and not confirmed:
        raise ValueError(f"live mode requires confirmation: {LIVE_CONFIRMATION}")
    store.set(_MODE_KEY, normalized)
    store.set(_CONFIRMED_KEY, "true" if confirmed else "false")
    return ExecutionPreferences(mode=normalized, live_confirmed=confirmed)


def kill_switch(store: SecretsStore | None = None) -> ExecutionPreferences:
    return save_execution_preferences(mode="paper", store=store)