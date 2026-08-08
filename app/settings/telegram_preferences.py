"""Telegram notification settings stored in the encrypted secrets store.

All values are optional. Missing values fall back to environment variables or
remain disabled until explicitly configured through the dashboard.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from app.settings.store import SecretsStore, get_secrets_store

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TelegramPreferences:
    enabled: bool = False
    bot_token_masked: str = ""
    chat_id_masked: str = ""
    updated_at: str | None = None


def load_telegram_preferences(
    store: SecretsStore | None = None,
    *,
    from_env: bool = True,
) -> TelegramPreferences:
    """Load Telegram notification preferences.
    
    Priority order:
    1. Values in encrypted store (if explicitly saved there)
    2. Environment variables (from .env file)
    3. Empty defaults
    
    This ensures sync between .env file and dashboard display.
    
    Args:
        store: SecretsStore instance
        from_env: If True, read from .env file as primary source
    
    Returns:
        TelegramPreferences with masked values for display
    """
    store = store or get_secrets_store()
    store_token = store.get("telegram.bot_token") or ""
    store_chat_id = store.get("telegram.chat_id") or ""
    stored_enabled = store.get("telegram.enabled")
    store_enabled = stored_enabled is not None and stored_enabled.lower() == "true"

    # The encrypted store is authoritative after dashboard configuration. Env
    # values remain a bootstrap fallback for existing deployments only.
    if stored_enabled is not None or store_token or store_chat_id or not from_env:
        bot_token = store_token
        chat_id = store_chat_id
        enabled = store_enabled
    else:
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
        enabled = os.getenv("TELEGRAM_ENABLED", "false").lower() == "true"
    
    # Mask values for display (show last 4 chars only)
    bot_token_masked = _mask_value(bot_token) if bot_token else ""
    chat_id_masked = _mask_value(chat_id) if chat_id else ""
    
    record = store.get_record("telegram.enabled")
    updated_at = record.updated_at if record else None
    
    return TelegramPreferences(
        enabled=enabled,
        bot_token_masked=bot_token_masked,
        chat_id_masked=chat_id_masked,
        updated_at=updated_at,
    )


def save_telegram_preferences(
    *,
    bot_token: str | None = None,
    chat_id: str | None = None,
    enabled: bool | None = None,
    store: SecretsStore | None = None,
    update_env_file: bool = True,
) -> TelegramPreferences:
    """Save Telegram notification preferences to BOTH secrets store AND .env file.
    
    This ensures synchronization between encrypted storage and .env configuration.
    
    Args:
        bot_token: Bot token string, or None to clear
        chat_id: Chat ID string, or None to clear
        enabled: Enable/disable flag
        store: SecretsStore instance
        update_env_file: If True, also update .env file (default: True)
    
    Returns:
        Updated TelegramPreferences with masked values
    """
    store = store or get_secrets_store()
    
    # Update encrypted store
    if enabled is not None:
        store.set("telegram.enabled", "true" if enabled else "false")
    
    if bot_token is not None:
        if bot_token.strip():
            store.set("telegram.bot_token", bot_token.strip())
        else:
            store.delete("telegram.bot_token")
    
    if chat_id is not None:
        if chat_id.strip():
            store.set("telegram.chat_id", chat_id.strip())
        else:
            store.delete("telegram.chat_id")
    
    return load_telegram_preferences(store=store)


def clear_telegram_preferences(store: SecretsStore | None = None) -> TelegramPreferences:
    """Clear all Telegram notification preferences."""
    store = store or get_secrets_store()
    store.delete("telegram.enabled")
    store.delete("telegram.bot_token")
    store.delete("telegram.chat_id")
    return load_telegram_preferences(store=store)


def load_telegram_credentials(
    store: SecretsStore | None = None,
) -> tuple[str, str, bool]:
    """Return runtime credentials and enabled state from the authoritative store."""
    store = store or get_secrets_store()
    return (
        str(store.get("telegram.bot_token") or "").strip(),
        str(store.get("telegram.chat_id") or "").strip(),
        (store.get("telegram.enabled") or "false").lower() == "true",
    )


def _mask_value(value: str) -> str:
    """Mask a secret value, showing only the last 4 characters.
    
    Examples:
        "1234567890:AABCDef..." -> "...AABCDef..."
        "123456789" -> "....789"
    """
    if not value or len(value) <= 4:
        return "****"
    return "..." + value[-4:]
