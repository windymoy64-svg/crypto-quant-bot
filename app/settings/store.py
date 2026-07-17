"""Encrypted key-value store for bot secrets (API keys, tokens, etc.)."""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

from cryptography.fernet import Fernet, InvalidToken


logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path("data/bot.db")
DEFAULT_KEY_FILE = Path("data/.bot_secret_key")


class SecretsStoreError(RuntimeError):
    """Base error for the secrets store."""


class SecretsStoreDecryptionError(SecretsStoreError):
    """Raised when a stored value cannot be decrypted with the current key."""


@dataclass(frozen=True)
class SecretRecord:
    key: str
    value: str
    updated_at: str


def _load_or_create_key(key_file: Path) -> bytes:
    env_value = os.getenv("BOT_SECRET_KEY", "").strip()
    if env_value:
        return env_value.encode("utf-8")

    if key_file.exists():
        raw = key_file.read_bytes().strip()
        if raw:
            return raw

    key_file.parent.mkdir(parents=True, exist_ok=True)
    new_key = Fernet.generate_key()
    key_file.write_bytes(new_key)
    try:
        key_file.chmod(0o600)
    except OSError:  # pragma: no cover - Windows / restricted FS
        logger.warning("Could not chmod 600 on %s", key_file)
    logger.warning(
        "Generated new BOT_SECRET_KEY at %s. Back it up; losing this file "
        "makes stored secrets unreadable.",
        key_file,
    )
    return new_key



class SecretsStore:
    """Thin SQLite-backed Fernet secrets store."""

    def __init__(
        self,
        database_path: str | Path = DEFAULT_DB_PATH,
        *,
        key_file: str | Path = DEFAULT_KEY_FILE,
    ) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._key_file = Path(key_file)
        self._fernet = Fernet(_load_or_create_key(self._key_file))
        self._lock = threading.Lock()
        self._ensure_schema()

    def set(self, key: str, value: str) -> None:
        if not key:
            raise ValueError("secret key must be non-empty")
        token = self._fernet.encrypt(value.encode("utf-8"))
        timestamp = datetime.now(UTC).isoformat(timespec="seconds")
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO secrets (key, value_encrypted, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_encrypted = excluded.value_encrypted,
                    updated_at = excluded.updated_at
                """,
                (key, token, timestamp),
            )

    def get(self, key: str) -> str | None:
        record = self.get_record(key)
        return record.value if record is not None else None

    def get_record(self, key: str) -> SecretRecord | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT key, value_encrypted, updated_at FROM secrets WHERE key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        try:
            value = self._fernet.decrypt(row[1]).decode("utf-8")
        except InvalidToken as exc:
            raise SecretsStoreDecryptionError(
                f"Could not decrypt secret {key!r}: encryption key mismatch or corrupted value"
            ) from exc
        return SecretRecord(key=str(row[0]), value=value, updated_at=str(row[2]))

    def delete(self, key: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM secrets WHERE key = ?", (key,))

    def delete_many(self, keys: Iterable[str]) -> None:
        keys_tuple = tuple(keys)
        if not keys_tuple:
            return
        placeholders = ",".join("?" for _ in keys_tuple)
        with self._lock, self._connect() as connection:
            connection.execute(
                f"DELETE FROM secrets WHERE key IN ({placeholders})",
                keys_tuple,
            )

    def has(self, key: str) -> bool:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM secrets WHERE key = ?", (key,)
            ).fetchone()
        return row is not None

    def updated_at(self, key: str) -> str | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT updated_at FROM secrets WHERE key = ?", (key,)
            ).fetchone()
        return str(row[0]) if row else None

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    def _ensure_schema(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS secrets (
                    key TEXT PRIMARY KEY,
                    value_encrypted BLOB NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )


_default_store: SecretsStore | None = None
_default_store_lock = threading.Lock()


def get_secrets_store() -> SecretsStore:
    """Return a process-wide singleton store using default paths."""

    global _default_store
    if _default_store is None:
        with _default_store_lock:
            if _default_store is None:
                _default_store = SecretsStore()
    return _default_store


def reset_default_store_for_tests() -> None:
    """Reset the module-level singleton. Only intended for tests."""

    global _default_store
    with _default_store_lock:
        _default_store = None
