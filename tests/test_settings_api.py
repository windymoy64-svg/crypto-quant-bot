from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.dashboard.app import create_app
from app.settings import exchange_credentials as ec_module
from app.settings import store as store_module
from app.settings.store import SecretsStore


@pytest.fixture()
def isolated_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SecretsStore:
    monkeypatch.delenv("BOT_SECRET_KEY", raising=False)
    monkeypatch.delenv("BOT_API_KEY", raising=False)
    store = SecretsStore(
        database_path=tmp_path / "bot.db",
        key_file=tmp_path / ".bot_secret_key",
    )
    monkeypatch.setattr(store_module, "get_secrets_store", lambda: store)
    monkeypatch.setattr(ec_module, "get_secrets_store", lambda: store)
    return store


@pytest.fixture()
def client(isolated_store: SecretsStore) -> TestClient:
    return TestClient(create_app())


def test_get_exchange_settings_returns_not_configured_by_default(client: TestClient) -> None:
    response = client.get("/api/settings/exchange")

    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is False
    assert body["api_key_masked"] == ""
    assert body["testnet"] is False


def test_put_exchange_settings_stores_credentials(
    client: TestClient, isolated_store: SecretsStore
) -> None:
    response = client.put(
        "/api/settings/exchange",
        json={
            "api_key": "abcdefghij1234567890",
            "api_secret": "supersecretvalue",
            "testnet": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is True
    assert body["testnet"] is True
    # Plaintext never leaves the server: only masked suffix is returned.
    assert body["api_key_masked"].endswith("7890")
    assert "abcdefghij" not in body["api_key_masked"]
    # But the stored value remains intact.
    assert isolated_store.get("binance.api_key") == "abcdefghij1234567890"
    assert isolated_store.get("binance.api_secret") == "supersecretvalue"


def test_put_exchange_settings_rejects_empty_payload(client: TestClient) -> None:
    response = client.put(
        "/api/settings/exchange",
        json={"api_key": "", "api_secret": ""},
    )

    assert response.status_code == 400


def test_delete_exchange_settings_clears_store(
    client: TestClient, isolated_store: SecretsStore
) -> None:
    client.put(
        "/api/settings/exchange",
        json={"api_key": "k", "api_secret": "s", "testnet": False},
    )

    response = client.delete("/api/settings/exchange")

    assert response.status_code == 200
    assert response.json()["configured"] is False
    assert isolated_store.get("binance.api_key") is None


def test_test_exchange_settings_requires_stored_or_body_credentials(
    client: TestClient,
) -> None:
    response = client.post("/api/settings/exchange/test", json={})

    assert response.status_code == 400


def test_test_exchange_settings_reports_network_failure(
    client: TestClient, isolated_store: SecretsStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.dashboard.routes import settings as settings_route
    import urllib.error

    def fake_urlopen(*args, **kwargs):
        raise urllib.error.URLError("dns failure")

    monkeypatch.setattr(settings_route.urllib.request, "urlopen", fake_urlopen)

    client.put(
        "/api/settings/exchange",
        json={"api_key": "k", "api_secret": "s", "testnet": True},
    )
    response = client.post("/api/settings/exchange/test", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert "network_error" in body["error"]
    assert body["testnet"] is True


def test_test_exchange_bitunix_sends_custom_user_agent(
    client: TestClient, isolated_store: SecretsStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bitunix' Cloudflare edge blocks the default ``Python-urllib`` UA with
    a 403 + ``error code: 1010``. The route must send a plausible UA so the
    request reaches the Bitunix API instead of being killed at the edge.
    """

    from app.dashboard.routes import settings as settings_route
    import io
    import json as _json

    captured: dict[str, object] = {}

    class _FakeResponse:
        def __init__(self, payload: bytes) -> None:
            self._buf = io.BytesIO(payload)

        def read(self) -> bytes:
            return self._buf.read()

        def __enter__(self) -> "_FakeResponse":
            return self

        def __exit__(self, *_exc: object) -> None:
            self._buf.close()

    def fake_urlopen(request, *args, **kwargs):
        captured["headers"] = dict(request.headers)
        captured["url"] = request.full_url
        return _FakeResponse(_json.dumps({"code": 0, "data": [], "msg": "ok"}).encode())

    monkeypatch.setattr(settings_route.urllib.request, "urlopen", fake_urlopen)

    client.put(
        "/api/settings/exchange",
        json={
            "exchange": "bitunix",
            "api_key": "bitunix_key",
            "api_secret": "bitunix_secret",
        },
    )
    response = client.post(
        "/api/settings/exchange/test", json={"exchange": "bitunix"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    # urllib normalises header names to ``Title-Case``.
    ua = captured["headers"].get("User-agent") or captured["headers"].get("User-Agent")
    assert ua == settings_route.BITUNIX_USER_AGENT
    assert "Python-urllib" not in (ua or "")
    assert "fapi.bitunix.com" in str(captured["url"])
