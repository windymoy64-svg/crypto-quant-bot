from __future__ import annotations

import pytest

from app.settings.exchange_credentials import (
    clear_exchange_credentials,
    load_exchange_credentials,
    mask_secret,
    save_exchange_credentials,
)
from app.settings.store import (
    SecretsStore,
    SecretsStoreDecryptionError,
)


@pytest.fixture()
def store(tmp_path, monkeypatch: pytest.MonkeyPatch) -> SecretsStore:
    monkeypatch.delenv("BOT_SECRET_KEY", raising=False)
    return SecretsStore(
        database_path=tmp_path / "bot.db",
        key_file=tmp_path / ".bot_secret_key",
    )


def test_store_set_get_roundtrip(store: SecretsStore) -> None:
    store.set("binance.api_key", "super-secret-key")

    assert store.get("binance.api_key") == "super-secret-key"
    assert store.has("binance.api_key") is True
    assert store.updated_at("binance.api_key") is not None


def test_store_returns_none_for_missing_key(store: SecretsStore) -> None:
    assert store.get("unknown") is None
    assert store.has("unknown") is False


def test_store_overwrite_updates_value_and_timestamp(store: SecretsStore) -> None:
    store.set("token", "first")
    first_updated = store.updated_at("token")
    store.set("token", "second")

    assert store.get("token") == "second"
    assert store.updated_at("token") is not None
    assert store.updated_at("token") >= first_updated


def test_store_delete_removes_value(store: SecretsStore) -> None:
    store.set("k", "v")
    store.delete("k")

    assert store.get("k") is None
    assert store.has("k") is False


def test_store_rejects_empty_key(store: SecretsStore) -> None:
    with pytest.raises(ValueError):
        store.set("", "value")


def test_store_raises_on_key_mismatch(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BOT_SECRET_KEY", raising=False)
    key_file = tmp_path / ".bot_secret_key"
    db_path = tmp_path / "bot.db"

    original = SecretsStore(database_path=db_path, key_file=key_file)
    original.set("token", "hello")

    # Rotate the encryption key while keeping the database intact -> decrypt fails.
    from cryptography.fernet import Fernet

    key_file.write_bytes(Fernet.generate_key())
    rotated = SecretsStore(database_path=db_path, key_file=key_file)

    with pytest.raises(SecretsStoreDecryptionError):
        rotated.get("token")


def test_save_and_load_exchange_credentials(store: SecretsStore) -> None:
    record = save_exchange_credentials(
        "abcdef1234567890abcd", "xyz-secret", testnet=True, store=store
    )

    assert record.api_key == "abcdef1234567890abcd"
    assert record.api_secret == "xyz-secret"
    assert record.testnet is True
    assert record.is_configured

    loaded = load_exchange_credentials(store=store)
    assert loaded is not None
    assert loaded.api_key == "abcdef1234567890abcd"
    assert loaded.testnet is True


def test_load_exchange_credentials_returns_none_when_missing(
    store: SecretsStore,
) -> None:
    assert load_exchange_credentials(store=store) is None


def test_clear_exchange_credentials(store: SecretsStore) -> None:
    save_exchange_credentials("k", "s", store=store)
    clear_exchange_credentials(store=store)

    assert load_exchange_credentials(store=store) is None


def test_save_rejects_empty_credentials(store: SecretsStore) -> None:
    with pytest.raises(ValueError):
        save_exchange_credentials("", "secret", store=store)
    with pytest.raises(ValueError):
        save_exchange_credentials("key", "", store=store)


def test_mask_secret_hides_all_but_last_chars() -> None:
    assert mask_secret("abcdefghij") == "******ghij"
    assert mask_secret("abc") == "***"
    assert mask_secret("") == ""
    assert mask_secret("abcdefghij", keep=2) == "********ij"
