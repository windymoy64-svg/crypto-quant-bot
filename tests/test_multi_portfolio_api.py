from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.dashboard.app import create_app
from app.dashboard.routes import multi_portfolio as multi_route
from app.settings import exchange_credentials as ec_module
from app.settings import execution_preferences as ep_module
from app.settings import portfolio_preferences as pp_module
from app.settings import store as store_module
from app.settings.exchange_credentials import save_exchange_credentials
from app.settings.execution_preferences import LIVE_CONFIRMATION
from app.settings.store import SecretsStore


@pytest.fixture(autouse=True)
def _reset_multi_portfolio_cache() -> None:
    """Reset in-memory TTL cache sebelum setiap test agar test tidak saling
    mempengaruhi melalui cache /api/portfolio/multi."""
    multi_route._multi_cache_payload = None
    multi_route._multi_cache_expires_at = 0.0


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
    monkeypatch.setattr(ep_module, "get_secrets_store", lambda: store)
    monkeypatch.setattr(pp_module, "get_secrets_store", lambda: store)
    return store


@pytest.fixture()
def client(isolated_store: SecretsStore) -> TestClient:
    return TestClient(create_app())


def test_portfolio_settings_default_to_safe_single_exchange(client: TestClient) -> None:
    response = client.get("/api/settings/portfolio")

    assert response.status_code == 200
    assert response.json() == {
        "view_mode": "single",
        "multi_exchange_enabled": False,
        "active_execution_exchange": "binance",
        "execution_scope": "single_exchange",
        "read_only_aggregation": True,
    }


def test_execution_mode_defaults_to_paper_and_supports_dry_run(client: TestClient) -> None:
    response = client.get("/api/settings/execution")
    assert response.status_code == 200
    assert response.json()["mode"] == "paper"

    saved = client.put(
        "/api/settings/execution", json={"mode": "dry_run"}
    )
    assert saved.status_code == 200
    assert saved.json()["mode"] == "dry_run"
    assert saved.json()["network_enabled"] is False


def test_live_mode_requires_credentials_and_exact_confirmation(
    client: TestClient, isolated_store: SecretsStore
) -> None:
    missing = client.put(
        "/api/settings/execution",
        json={"mode": "live", "confirmation": LIVE_CONFIRMATION},
    )
    assert missing.status_code == 400
    assert "credentials_missing" in missing.json()["detail"]

    client.put(
        "/api/settings/portfolio",
        json={"view_mode": "single", "active_execution_exchange": "bitunix"},
    )
    save_exchange_credentials(
        "bitunix-key", "bitunix-secret", exchange="bitunix", store=isolated_store
    )
    from app.dashboard.routes import settings as settings_route
    original_preflight = settings_route._perform_bitunix_test
    settings_route._perform_bitunix_test = lambda *_args, **_kwargs: {"ok": True}
    wrong = client.put(
        "/api/settings/execution",
        json={"mode": "live", "confirmation": "YES"},
    )
    assert wrong.status_code == 400

    try:
        live = client.put(
            "/api/settings/execution",
            json={"mode": "live", "confirmation": LIVE_CONFIRMATION},
        )
        assert live.status_code == 200
        assert live.json()["mode"] == "live"
        assert live.json()["network_enabled"] is True
    finally:
        settings_route._perform_bitunix_test = original_preflight


def test_execution_kill_switch_returns_to_paper(client: TestClient) -> None:
    client.put("/api/settings/execution", json={"mode": "dry_run"})
    stopped = client.post("/api/settings/execution/kill", json={})
    assert stopped.status_code == 200
    assert stopped.json()["mode"] == "paper"
    assert stopped.json()["network_enabled"] is False


def test_portfolio_settings_enable_multi_view_but_keep_single_executor(
    client: TestClient,
) -> None:
    response = client.put(
        "/api/settings/portfolio",
        json={"view_mode": "multi", "active_execution_exchange": "bitunix"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["multi_exchange_enabled"] is True
    assert body["active_execution_exchange"] == "bitunix"
    assert body["execution_scope"] == "single_exchange"


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"view_mode": "all"}, "view mode"),
        ({"active_execution_exchange": "unknown"}, "exchange"),
    ],
)
def test_portfolio_settings_reject_invalid_values(
    client: TestClient, payload: dict[str, str], expected: str
) -> None:
    response = client.put("/api/settings/portfolio", json=payload)

    assert response.status_code == 400
    assert expected in response.json()["detail"].lower()


def test_multi_portfolio_does_not_call_network_without_credentials(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        multi_route,
        "_perform_binance_test",
        lambda *_args, **_kwargs: pytest.fail("network helper must not be called"),
    )
    monkeypatch.setattr(
        multi_route,
        "_perform_bitunix_test",
        lambda *_args, **_kwargs: pytest.fail("network helper must not be called"),
    )

    response = client.get("/api/portfolio/multi")

    assert response.status_code == 200
    body = response.json()
    assert body["accounts_configured"] == 0
    assert body["accounts_connected"] == 0
    assert [item["status"] for item in body["accounts"]] == [
        "not_configured",
        "not_configured",
    ]


def test_multi_portfolio_returns_both_accounts_without_false_cross_asset_total(
    client: TestClient,
    isolated_store: SecretsStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save_exchange_credentials(
        "binance-key",
        "binance-secret",
        exchange="binance",
        store=isolated_store,
    )
    save_exchange_credentials(
        "bitunix-key",
        "bitunix-secret",
        exchange="bitunix",
        store=isolated_store,
    )
    monkeypatch.setattr(
        multi_route,
        "_perform_binance_test",
        lambda *_args, **_kwargs: {
            "ok": True,
            "testnet": False,
            "balances": [
                {"asset": "USDT", "free": "100", "locked": "5"},
                {"asset": "BTC", "free": "0.01", "locked": "0"},
            ],
        },
    )
    monkeypatch.setattr(
        multi_route,
        "_load_binance_details",
        lambda *_args, **_kwargs: {
            "balances": [], "positions": [], "open_orders": [], "warnings": []
        },
    )
    monkeypatch.setattr(
        multi_route,
        "_load_bitunix_details",
        lambda *_args, **_kwargs: {
            "balances": [], "positions": [], "open_orders": [], "warnings": []
        },
    )
    monkeypatch.setattr(
        multi_route,
        "_perform_bitunix_test",
        lambda *_args, **_kwargs: {
            "ok": True,
            "testnet": False,
            "margin_coin": "USDT",
            "available": "250",
            "cross_unrealized_pnl": "3.5",
            "isolation_unrealized_pnl": "-1",
        },
    )
    monkeypatch.setattr(
        multi_route,
        "_load_bitunix_details",
        lambda *_args, **_kwargs: {
            "balances": [], "positions": [], "open_orders": [], "warnings": []
        },
    )

    response = client.get("/api/portfolio/multi")

    assert response.status_code == 200
    body = response.json()
    assert body["accounts_configured"] == 2
    assert body["accounts_connected"] == 2
    assert body["read_only"] is True
    assert "total_balance" not in body
    assert "total_equity" not in body
    by_exchange = {item["exchange"]: item for item in body["accounts"]}
    assert by_exchange["binance"]["balances"][0]["asset"] == "USDT"
    assert by_exchange["bitunix"]["balances"][0]["available"] == "250"
    assert by_exchange["bitunix"]["balances"][0]["unrealized_pnl"] == 2.5


def test_multi_portfolio_keeps_healthy_exchange_when_other_exchange_fails(
    client: TestClient,
    isolated_store: SecretsStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for exchange in ("binance", "bitunix"):
        save_exchange_credentials(
            f"{exchange}-key",
            f"{exchange}-secret",
            exchange=exchange,
            store=isolated_store,
        )
    monkeypatch.setattr(
        multi_route,
        "_perform_binance_test",
        lambda *_args, **_kwargs: {
            "ok": False,
            "error": "invalid key",
            "testnet": False,
        },
    )
    monkeypatch.setattr(
        multi_route,
        "_perform_bitunix_test",
        lambda *_args, **_kwargs: {
            "ok": True,
            "testnet": False,
            "margin_coin": "USDT",
            "available": "25",
        },
    )

    body = client.get("/api/portfolio/multi").json()

    assert body["accounts_connected"] == 1
    by_exchange = {item["exchange"]: item for item in body["accounts"]}
    assert by_exchange["binance"]["status"] == "connection_error"
    assert by_exchange["bitunix"]["status"] == "connected"


def test_connection_helper_exception_is_isolated_to_its_exchange(
    client: TestClient,
    isolated_store: SecretsStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save_exchange_credentials(
        "bitunix-key", "bitunix-secret", exchange="bitunix", store=isolated_store
    )
    monkeypatch.setattr(
        multi_route,
        "_perform_bitunix_test",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyError("unexpected data")),
    )

    response = client.get("/api/portfolio/multi")

    assert response.status_code == 200
    bitunix = next(
        account for account in response.json()["accounts"]
        if account["exchange"] == "bitunix"
    )
    assert bitunix["status"] == "connection_error"


def test_multi_portfolio_aggregates_only_visible_usdt_positions_and_orders(
    client: TestClient,
    isolated_store: SecretsStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for exchange in ("binance", "bitunix"):
        save_exchange_credentials(
            f"{exchange}-key",
            f"{exchange}-secret",
            exchange=exchange,
            store=isolated_store,
        )
    client.put(
        "/api/settings/portfolio",
        json={"view_mode": "multi", "active_execution_exchange": "binance"},
    )
    monkeypatch.setattr(
        multi_route,
        "_perform_binance_test",
        lambda *_args, **_kwargs: {
            "ok": True,
            "testnet": False,
            "balances": [
                {"asset": "USDT", "free": "100", "locked": "0"},
                {"asset": "BTC", "free": "1", "locked": "0"},
            ],
        },
    )
    monkeypatch.setattr(
        multi_route,
        "_perform_bitunix_test",
        lambda *_args, **_kwargs: {
            "ok": True,
            "testnet": False,
            "margin_coin": "USDT",
            "available": "250",
        },
    )
    monkeypatch.setattr(
        multi_route,
        "_load_binance_details",
        lambda *_args, **_kwargs: {
            "balances": [
                {"asset": "USDT", "available_balance": 50, "wallet": "futures"}
            ],
            "positions": [{"exchange": "binance", "symbol": "BTCUSDT"}],
            "open_orders": [{"exchange": "binance", "order_id": 1}],
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        multi_route,
        "_load_bitunix_details",
        lambda *_args, **_kwargs: {
            "balances": [],
            "positions": [{"exchange": "bitunix", "symbol": "ETHUSDT"}],
            "open_orders": [{"exchange": "bitunix", "order_id": "2"}],
            "warnings": [],
        },
    )

    body = client.get("/api/portfolio/multi").json()

    assert body["available_balance_usdt"] == 400
    assert body["open_positions_count"] == 2
    assert body["open_orders_count"] == 2
    assert body["displayed_exchanges"] == ["binance", "bitunix"]
    assert {row["exchange"] for row in body["positions"]} == {"binance", "bitunix"}


def test_bitunix_private_get_is_signed_and_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    captured: dict[str, object] = {}

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self) -> bytes:
            return json.dumps({"code": 0, "data": {"positionList": []}}).encode()

    def fake_urlopen(request, timeout):
        captured["method"] = request.method
        captured["url"] = request.full_url
        captured["headers"] = dict(request.headers)
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(multi_route.urllib.request, "urlopen", fake_urlopen)

    data = multi_route._bitunix_private_get(
        "key", "secret", "/api/v1/futures/position/get_pending_positions"
    )

    assert data == {"positionList": []}
    assert captured["method"] == "GET"
    assert "get_pending_positions" in str(captured["url"])
    headers = {str(key).lower(): value for key, value in captured["headers"].items()}
    assert headers.get("api-key") == "key"
    assert headers.get("sign")


def test_multi_portfolio_does_not_sum_testnet_with_mainnet(
    client: TestClient,
    isolated_store: SecretsStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save_exchange_credentials(
        "binance-key", "binance-secret", testnet=True,
        exchange="binance", store=isolated_store,
    )
    save_exchange_credentials(
        "bitunix-key", "bitunix-secret",
        exchange="bitunix", store=isolated_store,
    )
    client.put(
        "/api/settings/portfolio",
        json={"view_mode": "multi", "active_execution_exchange": "binance"},
    )
    monkeypatch.setattr(
        multi_route,
        "_perform_binance_test",
        lambda *_args, **_kwargs: {
            "ok": True, "testnet": True,
            "balances": [{"asset": "USDT", "free": "100", "locked": "0"}],
        },
    )
    monkeypatch.setattr(
        multi_route,
        "_perform_bitunix_test",
        lambda *_args, **_kwargs: {
            "ok": True, "testnet": False, "margin_coin": "USDT", "available": "200",
        },
    )
    empty_details = {
        "balances": [], "positions": [], "open_orders": [], "warnings": []
    }
    monkeypatch.setattr(
        multi_route, "_load_binance_details", lambda *_args, **_kwargs: empty_details
    )
    monkeypatch.setattr(
        multi_route, "_load_bitunix_details", lambda *_args, **_kwargs: empty_details
    )

    body = client.get("/api/portfolio/multi").json()

    assert body["account_environment"] == "mixed"
    assert body["available_balance_usdt"] is None