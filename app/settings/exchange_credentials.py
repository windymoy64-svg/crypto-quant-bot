"""High-level helpers for storing exchange API credentials.

Supports multiple exchanges (Binance, Bitunix, ...) by prefixing the
underlying secret keys with the exchange identifier. The dashboard Settings
panel reads/writes credentials through this module so callers do not touch
raw secret keys directly.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.settings.store import SecretsStore, get_secrets_store


DEFAULT_EXCHANGE = "binance"
SUPPORTED_EXCHANGES: tuple[str, ...] = ("binance", "bitunix")


def _normalize_exchange(exchange: str | None) -> str:
    value = (exchange or DEFAULT_EXCHANGE).strip().lower()
    if value not in SUPPORTED_EXCHANGES:
        raise ValueError(
            f"Unsupported exchange {value!r}; expected one of {SUPPORTED_EXCHANGES}"
        )
    return value


def _keys(exchange: str) -> tuple[str, str, str]:
    prefix = _normalize_exchange(exchange)
    return (f"{prefix}.api_key", f"{prefix}.api_secret", f"{prefix}.testnet")


# Backwards-compatible constants pointing at the default (Binance) prefix.
EXCHANGE_API_KEY, EXCHANGE_API_SECRET, EXCHANGE_TESTNET_FLAG = _keys(DEFAULT_EXCHANGE)


@dataclass(frozen=True)
class ExchangeCredentialsRecord:
    api_key: str
    api_secret: str
    testnet: bool
    updated_at: str | None
    exchange: str = DEFAULT_EXCHANGE

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_secret)


def load_exchange_credentials(
    store: SecretsStore | None = None,
    *,
    exchange: str = DEFAULT_EXCHANGE,
) -> ExchangeCredentialsRecord | None:
    store = store or get_secrets_store()
    exchange = _normalize_exchange(exchange)
    key_k, secret_k, testnet_k = _keys(exchange)
    key_record = store.get_record(key_k)
    if key_record is None:
        return None
    secret_record = store.get_record(secret_k)
    if secret_record is None:
        return None
    testnet_raw = store.get(testnet_k) or "false"
    updated_at = max(
        key_record.updated_at,
        secret_record.updated_at,
    )
    return ExchangeCredentialsRecord(
        api_key=key_record.value,
        api_secret=secret_record.value,
        testnet=testnet_raw.strip().lower() in {"1", "true", "yes", "on"},
        updated_at=updated_at,
        exchange=exchange,
    )


def save_exchange_credentials(
    api_key: str,
    api_secret: str,
    *,
    testnet: bool = False,
    store: SecretsStore | None = None,
    exchange: str = DEFAULT_EXCHANGE,
) -> ExchangeCredentialsRecord:
    if not api_key or not api_secret:
        raise ValueError("api_key and api_secret must be non-empty")
    store = store or get_secrets_store()
    exchange = _normalize_exchange(exchange)
    key_k, secret_k, testnet_k = _keys(exchange)
    store.set(key_k, api_key.strip())
    store.set(secret_k, api_secret.strip())
    store.set(testnet_k, "true" if testnet else "false")
    record = load_exchange_credentials(store=store, exchange=exchange)
    assert record is not None  # just wrote it
    return record


def clear_exchange_credentials(
    store: SecretsStore | None = None,
    *,
    exchange: str = DEFAULT_EXCHANGE,
) -> None:
    store = store or get_secrets_store()
    store.delete_many(list(_keys(exchange)))


def mask_secret(value: str, *, keep: int = 4) -> str:
    """Return ``value`` with everything but the last ``keep`` chars masked.

    Empty strings pass through unchanged.
    """

    if not value:
        return ""
    if len(value) <= keep:
        return "*" * len(value)
    return "*" * (len(value) - keep) + value[-keep:]
