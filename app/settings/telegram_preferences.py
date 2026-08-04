"""Telegram notification settings stored in the encrypted secrets store.

All values are optional. Missing values fall back to environment variables or
remain disabled until explicitly configured through the dashboard.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

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
    import os
    
    # Primary source: .env file (for sync)
    env_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    env_chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    env_enabled = os.getenv("TELEGRAM_ENABLED", "false").lower() == "true"
    
    # Secondary source: encrypted store (for persistence across deployments)
    store_token = store.get("telegram.bot_token") or ""
    store_chat_id = store.get("telegram.chat_id") or ""
    store_enabled = (store.get("telegram.enabled") or "").lower() == "true"
    
    # Use env values if available (primary sync source)
    # Otherwise fall back to store values
    bot_token = env_token if env_token else store_token
    chat_id = env_chat_id if env_chat_id else store_chat_id
    enabled = env_enabled if env_enabled else store_enabled
    
    # Mask values for display (show last 4 chars only)
    bot_token_masked = _mask_value(bot_token) if bot_token else ""
    chat_id_masked = _mask_value(chat_id) if chat_id else ""
    
    # Auto-enable if both token and chat_id exist
    if enabled is False and bot_token and chat_id:
        enabled = True
    
    # Get update timestamp from .env file mtime
    try:
        env_mtime = os.path.getmtime("/opt/crypto-quant-bot/.env")
        updated_at = "Telegram"  # Will be shown as "Auto-loaded from .env"
    except OSError:
        updated_at = None
    
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
    import os
    
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
    
    # Also update .env file for runtime access
    if update_env_file:
        env_path = "/opt/crypto-quant-bot/.env"
        if os.path.exists(env_path):
            try:
                with open(env_path, 'r') as f:
                    lines = f.readlines()
                
                updated = False
                new_lines = []
                for line in lines:
                    stripped = line.strip()
                    
                    if stripped.startswith("TELEGRAM_BOT_TOKEN="):
                        new_line = f"TELEGRAM_BOT_TOKEN={bot_token.strip()}\n" if bot_token else "# TELEGRAM_BOT_TOKEN=\n"
                        new_lines.append(new_line)
                        updated = True
                    elif stripped.startswith("TELEGRAM_CHAT_ID="):
                        new_line = f"TELEGRAM_CHAT_ID={chat_id.strip()}\n" if chat_id else "# TELEGRAM_CHAT_ID=\n"
                        new_lines.append(new_line)
                        updated = True
                    elif stripped.startswith("TELEGRAM_ENABLED="):
                        enabled_val = "true" if enabled else "false"
                        new_line = f"TELEGRAM_ENABLED={enabled_val}\n"
                        new_lines.append(new_line)
                        updated = True
                    else:
                        new_lines.append(line)
                
                if not updated:
                    # Append if no telegram lines found
                    new_lines.extend([
                        "\n",
                        "# Telegram settings\n",
                        f"TELEGRAM_BOT_TOKEN={bot_token.strip()}\n" if bot_token else "# TELEGRAM_BOT_TOKEN=\n",
                        f"TELEGRAM_CHAT_ID={chat_id.strip()}\n" if chat_id else "# TELEGRAM_CHAT_ID=\n",
                        f"TELEGRAM_ENABLED={'true' if enabled else 'false'}\n",
                    ])
                
                if updated:
                    with open(env_path, 'w') as f:
                        f.writelines(new_lines)
            except Exception as e:
                logger = logging.getLogger(__name__)
                logger.warning(f"Failed to update .env file: {e}")
    
    return load_telegram_preferences(store=store)


def clear_telegram_preferences(store: SecretsStore | None = None) -> TelegramPreferences:
    """Clear all Telegram notification preferences."""
    store = store or get_secrets_store()
    store.delete("telegram.enabled")
    store.delete("telegram.bot_token")
    store.delete("telegram.chat_id")
    return load_telegram_preferences(store=store)


def _mask_value(value: str) -> str:
    """Mask a secret value, showing only the last 4 characters.
    
    Examples:
        "1234567890:AABCDef..." -> "...AABCDef..."
        "123456789" -> "....789"
    """
    if not value or len(value) <= 4:
        return "****"
    return "..." + value[-4:]
