from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.dashboard.app import create_app
from app.dashboard.routes import futures as futures_route
from app.exchange.binance.auth import BinanceCredentials


@pytest.fixture()
def isolated_futures_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    monkeypatch.delenv("BOT_API_KEY", raising=False)
    monkeypatch.delenv("BINANCE_API_KEY", raising=False)
    monkeypatch.delenv("BINANCE_API_SECRET", raising=False)
    monkeypatch.delenv("EXCHANGE_API_KEY", raising=False)
    monkeypatch.delenv("EXCHANGE_SECRET", raising=False)
    config_path = tmp_path / "futures.json"

    # Point every routing helper at the temp file so we never touch the real
    # configs/ directory.
    monkeypatch.setattr(futures_route, "DEFAULT_CONFIG_PATH", config_path)

    return config_path


@pytest.fixture()
def client(isolated_futures_config: Path) -> TestClient:
    return TestClient(create_app())


def _stub_credentials(monkeypatch: pytest.MonkeyPatch, *, configured: bool) -> None:
    def fake_credentials(self, *, required: bool = False):
        return BinanceCredentials(
            api_key="key" if configured else "",
            api_secret="secret" if configured else "",
        )

    monkeypatch.setattr(
        "app.exchange.binance.auth.BinanceAuth.credentials", fake_credentials
    )


def test_get_returns_defaults_when_file_missing(client: TestClient) -> None:
    response = client.get("/api/settings/futures")

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is False
    assert body["venue"] == "usdm_futures"
    assert body["network"] == "testnet"
    assert body["default_leverage"] == 3
    assert body["symbols"] == []


def test_put_persists_config_atomically(
    client: TestClient, isolated_futures_config: Path
) -> None:
    payload = {
        "enabled": True,
        "network": "testnet",
        "position_mode": "one_way",
        "margin_type": "ISOLATED",
        "default_leverage": 5,
        "symbols": {"BTCUSDT": {"leverage": 10, "margin_type": "ISOLATED"}},
    }

    response = client.put("/api/settings/futures", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["default_leverage"] == 5
    assert body["symbols"] == [
        {"symbol": "BTCUSDT", "leverage": 10, "margin_type": "ISOLATED"}
    ]

    # File was written and parses back to the same shape.
    persisted = json.loads(isolated_futures_config.read_text())
    assert persisted["enabled"] is True
    assert persisted["symbols"]["BTCUSDT"]["leverage"] == 10


def test_put_rejects_invalid_leverage(client: TestClient) -> None:
    response = client.put(
        "/api/settings/futures",
        json={"enabled": True, "default_leverage": 999},
    )

    assert response.status_code == 400
    assert "leverage" in response.json()["detail"]


def test_put_rejects_unsupported_venue(client: TestClient) -> None:
    response = client.put(
        "/api/settings/futures",
        json={"enabled": True, "venue": "coinm_futures"},
    )

    assert response.status_code == 400


def test_bootstrap_returns_400_when_config_disabled(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_credentials(monkeypatch, configured=True)

    response = client.post("/api/settings/futures/bootstrap", json={})

    assert response.status_code == 400
    assert "bootstrap_skipped" in response.json()["detail"]


def test_bootstrap_returns_400_when_credentials_missing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, isolated_futures_config: Path
) -> None:
    isolated_futures_config.write_text(json.dumps({"enabled": True}))
    _stub_credentials(monkeypatch, configured=False)

    response = client.post("/api/settings/futures/bootstrap", json={})

    assert response.status_code == 400


def test_account_requires_credentials(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_credentials(monkeypatch, configured=False)

    response = client.get("/api/futures/account")

    assert response.status_code == 400
    assert "binance_credentials_missing" in response.json()["detail"]


def test_get_reports_credentials_configured_flag(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_credentials(monkeypatch, configured=True)

    response = client.get("/api/settings/futures")

    assert response.status_code == 200
    assert response.json()["credentials_configured"] is True


def test_put_normalizes_symbol_case(
    client: TestClient, isolated_futures_config: Path
) -> None:
    response = client.put(
        "/api/settings/futures",
        json={"enabled": True, "symbols": {"btcusdt": {"leverage": 3}}},
    )

    assert response.status_code == 200
    persisted = json.loads(isolated_futures_config.read_text())
    assert "BTCUSDT" in persisted["symbols"]
    assert "btcusdt" not in persisted["symbols"]
