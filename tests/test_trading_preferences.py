from __future__ import annotations

import pytest

from app.settings.store import SecretsStore
from app.settings.trading_preferences import (
    leverage_options,
    load_trading_preferences,
    save_trading_preferences,
)


@pytest.fixture()
def store(tmp_path, monkeypatch: pytest.MonkeyPatch) -> SecretsStore:
    monkeypatch.delenv("BOT_SECRET_KEY", raising=False)
    return SecretsStore(
        database_path=tmp_path / "bot.db",
        key_file=tmp_path / ".bot_secret_key",
    )


def test_preferences_roundtrip_and_clear(store: SecretsStore) -> None:
    saved = save_trading_preferences(
        store=store,
        exchange="bitunix",
        take_profit_percent=5.0,
        stop_loss_percent=2.0,
        trailing_stop_percent=1.0,
        leverage=25,
    )

    assert saved.take_profit_percent == 5.0
    assert saved.stop_loss_percent == 2.0
    assert saved.trailing_stop_percent == 1.0
    assert saved.leverage == 25

    cleared = save_trading_preferences(store=store, exchange="bitunix")
    assert cleared.take_profit_percent is None
    assert cleared.stop_loss_percent is None
    assert cleared.trailing_stop_percent is None
    assert cleared.leverage is None


def test_preferences_are_isolated_by_exchange(store: SecretsStore) -> None:
    save_trading_preferences(store=store, exchange="binance", leverage=10)

    assert load_trading_preferences(store=store, exchange="binance").leverage == 10
    assert load_trading_preferences(store=store, exchange="bitunix").leverage is None


def test_exchange_leverage_options_and_validation(store: SecretsStore) -> None:
    assert leverage_options("binance")[0] == 1
    assert leverage_options("binance")[-1] == 125
    assert leverage_options("bitunix")[0] == 1
    assert leverage_options("bitunix")[-1] == 125

    with pytest.raises(ValueError, match="leverage"):
        save_trading_preferences(store=store, exchange="bitunix", leverage=126)

    with pytest.raises(ValueError, match="take_profit_percent"):
        save_trading_preferences(
            store=store, exchange="binance", take_profit_percent=0
        )