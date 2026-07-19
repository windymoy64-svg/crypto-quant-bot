from pathlib import Path

import pytest

from app.settings.execution_preferences import (
    LIVE_CONFIRMATION,
    kill_switch,
    load_execution_preferences,
    save_execution_preferences,
)
from app.settings.store import SecretsStore


@pytest.fixture()
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SecretsStore:
    monkeypatch.delenv("BOT_SECRET_KEY", raising=False)
    return SecretsStore(
        database_path=tmp_path / "bot.db",
        key_file=tmp_path / ".secret",
    )


def test_execution_mode_defaults_to_paper(store: SecretsStore) -> None:
    assert load_execution_preferences(store).mode == "paper"


def test_live_requires_exact_confirmation(store: SecretsStore) -> None:
    with pytest.raises(ValueError, match="requires confirmation"):
        save_execution_preferences(mode="live", confirmation="yes", store=store)

    saved = save_execution_preferences(
        mode="live", confirmation=LIVE_CONFIRMATION, store=store,
    )
    assert saved.network_enabled is True


def test_kill_switch_returns_to_paper(store: SecretsStore) -> None:
    save_execution_preferences(
        mode="live", confirmation=LIVE_CONFIRMATION, store=store,
    )
    stopped = kill_switch(store)
    assert stopped.mode == "paper"
    assert stopped.network_enabled is False