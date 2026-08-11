from __future__ import annotations

from pathlib import Path
from datetime import UTC, datetime

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
            "frozen": "25",
            "margin": "10",
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
    assert by_exchange["bitunix"]["account_balance_usdt"] == 285
    assert by_exchange["bitunix"]["equity_usdt"] == 287.5


def test_bitunix_pending_order_normalization_includes_live_fields() -> None:
    row = {
        "orderId": "1", "symbol": "ETHUSDT", "qty": "0.006",
        "tradeQty": "0", "price": "1942.70", "side": "SELL",
        "orderType": "LIMIT", "status": "NEW_", "leverage": 20,
        "marginMode": "CROSS", "tpPrice": "1927.93", "slPrice": "1950.08",
        "ctime": 1785480480000, "mtime": 1785480481000,
    }

    order = multi_route._normalize_bitunix_order(row)

    assert order["executed_quantity"] == "0"
    assert order["status"] == "NEW"
    assert order["leverage"] == 20
    assert order["take_profit"] == "1927.93"
    assert order["stop_loss"] == "1950.08"
    assert order["created_at"].endswith("+00:00")


def test_bitunix_filled_market_order_normalizes_price_margin_pnl_and_reason() -> None:
    order = multi_route._normalize_bitunix_order({
        "orderId": "o1", "symbol": "LINKUSDT", "side": "BUY",
        "orderType": "MARKET", "status": "FILLED", "price": "MARKET",
        "qty": "1.44", "tradeQty": "1.44", "dealAvgPrice": "8.25",
        "reduceOnly": True, "leverage": 25,
        "realizedPNL": "0.02", "fee": "0.004",
    })

    assert order["price"] == "8.25"
    assert order["quantity"] == "1.44"
    assert order["notional"] == pytest.approx(11.88)
    assert order["modal"] == pytest.approx(0.4752)
    assert order["net_pnl"] == pytest.approx(0.016)
    assert order["reason"] == "position_reduced"


def test_bitunix_order_history_restores_exact_bot_close_reason() -> None:
    order = multi_route._normalize_bitunix_order(
        {
            "orderId": "exit-123", "symbol": "BTCUSDT", "side": "SELL",
            "orderType": "MARKET", "status": "FILLED", "qty": "0.1",
            "tradeQty": "0.1", "dealAvgPrice": "101", "reduceOnly": True,
        },
        {
            "exit-123": {
                "role": "exit", "reason": "choch_bearish_against_long",
            "position_id": "position-1",
                "metadata_kind": "bot_order",
            }
        },
    )

    assert order["reason"] == "choch_bearish_against_long"
    assert order["reason_source"] == "bot_order_metadata"
    assert order["close_scope"] == "full"
    assert order["close_label"] == "Full close — choch bearish against long"


def test_bitunix_entry_metadata_is_not_used_as_close_reason() -> None:
    order = multi_route._normalize_bitunix_order(
        {
            "orderId": "entry-123", "symbol": "BTCUSDT", "side": "BUY",
            "status": "FILLED", "qty": "0.1", "tradeQty": "0.1",
            "dealAvgPrice": "100", "reduceOnly": False,
        },
        {"entry-123": {"role": "entry", "reason": "entry"}},
    )

    assert order["reason"] == "entry_filled"
    assert order["reason_source"] == "bitunix_order_lifecycle"
    assert order["close_label"] is None


def test_bitunix_order_history_deduplicates_same_order_id() -> None:
    rows = multi_route._deduplicate_orders([
        {"exchange": "bitunix", "order_id": "1", "updated_at": "2026-01-01"},
        {"exchange": "bitunix", "order_id": "1", "updated_at": "2026-01-02"},
        {"exchange": "bitunix", "order_id": "2", "updated_at": "2026-01-01"},
    ])

    assert len(rows) == 2
    assert next(row for row in rows if row["order_id"] == "1")["updated_at"] == "2026-01-02"


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


def test_bitunix_position_normalization_preserves_attached_tp_sl() -> None:
    position = multi_route._normalize_bitunix_position({
        "symbol": "DOGEUSDT",
        "side": "SHORT",
        "qty": "80",
        "avgOpenPrice": "0.08948",
        "tpPrice": "0.08700",
        "slPrice": "0.09100",
        "ctime": 1691382137448,
    })

    assert position["take_profit"] == "0.08700"
    assert position["stop_loss"] == "0.09100"
    assert position["opened_at"].endswith("+00:00")


def test_bitunix_position_normalization_supports_nested_and_multiple_tps() -> None:
    position = multi_route._normalize_bitunix_position({
        "symbol": "KAITOUSDT", "side": "BUY", "qty": "10",
        "avgOpenPrice": "1.0", "takeProfit": ["1.04", "1.06", "1.08"],
        "stopLoss": {"price": "0.98"},
    })

    assert position["take_profit"] == 1.04
    assert position["take_profits"] == [1.04, 1.06, 1.08]
    assert position["stop_loss"] == "0.98"


def test_bitunix_position_derives_mark_price_from_exchange_unrealized_pnl() -> None:
    position = multi_route._normalize_bitunix_position({
        "symbol": "BNBUSDT", "side": "BUY", "qty": "0.07",
        "avgOpenPrice": "593.24", "markPrice": None,
        "unrealizedPNL": "-0.2921",
    })

    assert position["mark_price"] == pytest.approx(589.0671428571)


def test_bitunix_pending_tpsl_is_attached_to_position() -> None:
    positions = [{"position_id": "p1", "symbol": "DOGEUSDT"}]
    multi_route._attach_bitunix_position_tpsl(positions, [{
        "positionId": "p1", "symbol": "DOGEUSDT",
        "tpPrice": "0.087", "slPrice": "0.091",
    }])

    assert positions[0]["take_profit"] == "0.087"
    assert positions[0]["stop_loss"] == "0.091"
    assert positions[0]["take_profit_order_count"] == 1
    assert positions[0]["stop_loss_order_count"] == 1


def test_bitunix_tpsl_falls_back_to_symbol_when_order_omits_position_id() -> None:
    positions = [{"position_id": "p1", "symbol": "DOGE/USDT"}]

    multi_route._attach_bitunix_position_tpsl(positions, [{
        "symbol": "DOGEUSDT",
        "takeProfit": {"price": "0.087"},
        "stopLoss": {"slTriggerPrice": "0.091"},
    }])

    assert positions[0]["take_profit"] == "0.087"
    assert positions[0]["stop_loss"] == "0.091"


def test_bitunix_tpsl_falls_back_to_symbol_when_position_id_rotates() -> None:
    positions = [{"position_id": "new-p1", "symbol": "TAO/USDT"}]

    multi_route._attach_bitunix_position_tpsl(positions, [{
        "positionId": "old-p1", "symbol": "TAOUSDT",
        "tpPrice": "350.0", "tpQty": "0.7",
    }])

    assert positions[0]["take_profit"] == "350.0"
    assert positions[0]["take_profit_total_quantity"] == pytest.approx(0.7)


def test_bitunix_details_loads_all_read_only_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths: list[str] = []

    def fake_get(_key, _secret, path, _params=None):
        paths.append(path)
        if "pending_positions" in path:
            return {"positionList": [{"positionId": "p1", "symbol": "BTCUSDT", "qty": "1"}]}
        if "tpsl" in path:
            return {"orderList": [{"positionId": "p1", "tpPrice": "70000"}]}
        if "history_orders" in path:
            return {"orderList": [{
                "orderId": "tp-1", "symbol": "ADAUSDT", "side": "SELL",
                "orderType": "LIMIT", "status": "FILLED", "qty": "11.5",
                "tradeQty": "11.5", "dealAvgPrice": "0.189",
                "reduceOnly": True, "realizedPNL": "0.0122",
            }]}
        if "history_positions" in path:
            now_ms = int(datetime.now(tz=UTC).timestamp() * 1000)
            return {"positionList": [{
                "positionId": "p0", "realizedPNL": "1.5", "mtime": now_ms,
            }]}
        return {"orderList": []}

    monkeypatch.setattr(multi_route, "_bitunix_private_get", fake_get)
    monkeypatch.setattr(multi_route, "_load_bitunix_order_metadata", lambda: {
        "tp-1": {"role": "take_profit_1", "reason": "take_profit_1", "status": "FILLED"},
    })

    details = multi_route._load_bitunix_details("key", "secret")

    assert len(paths) == 5
    assert details["positions"][0]["take_profit"] == "70000"
    assert details["closed_positions"][0]["net_pnl"] == pytest.approx(1.5)
    assert details["order_history"][0]["realized_pnl"] == pytest.approx(0.0122)
    assert details["warnings"] == []


def test_closed_position_history_is_current_session_one_row_with_bot_reason() -> None:
    positions = [
        {
            "position_id": "today-1", "symbol": "XRPUSDT", "side": "SHORT",
            "quantity": "4.6", "entry_price": "1.0644", "leverage": "25",
            "realized_pnl": 0.03, "closed_at": "2026-08-01T01:17:18+00:00",
        },
        {
            "position_id": "yesterday-1", "symbol": "LINKUSDT", "side": "SHORT",
            "quantity": "0.53", "entry_price": "8.16", "leverage": "25",
            "realized_pnl": -0.03, "closed_at": "2026-07-31T23:59:59+00:00",
        },
    ]
    metadata = {
        "exit-order": {
            "position_id": "today-1", "role": "exit",
            "reason": "structure_invalidation", "created_at": "2026-08-01T01:17:17+00:00",
            "status": "FILLED",
        },
        "entry-order": {
            "position_id": "today-1", "role": "entry", "reason": "entry",
        },
    }

    history = multi_route._build_closed_position_history(
        positions, metadata, now=datetime(2026, 8, 1, 4, 0, tzinfo=UTC),
    )

    assert len(history) == 1
    assert history[0]["position_id"] == "today-1"
    assert history[0]["price"] == pytest.approx(1.0644)
    assert history[0]["quantity"] == pytest.approx(4.6)
    assert history[0]["modal"] == pytest.approx(1.0644 * 4.6 / 25)
    assert history[0]["reason"] == "structure_invalidation"
    assert history[0]["reason_source"] == "bot_order_metadata"


def test_bitunix_closed_position_normalization_uses_net_pnl() -> None:
    position = multi_route._normalize_bitunix_closed_position({
        "positionId": "p1", "symbol": "BNBUSDT", "side": "LONG",
        "maxQty": "0.07", "entryPrice": "593.24", "closePrice": "592.29",
        "realizedPNL": "-0.0665", "fee": "0.01", "funding": "-0.002",
        "ctime": 1691382137448, "mtime": 1691385737448,
    })

    assert position["status"] == "CLOSED"
    assert position["net_pnl"] == pytest.approx(-0.0785)
    assert position["closed_at"]


def test_closed_position_reason_infers_stop_loss_from_exchange_price() -> None:
    history = multi_route._build_closed_position_history(
        [{
            "position_id": "sl-1", "symbol": "BTCUSDT", "side": "LONG",
            "quantity": 1, "entry_price": 100, "close_price": 94,
            "stop_loss": 95, "take_profit": 110,
            "realized_pnl": -6, "closed_at": "2026-08-01T01:00:00+00:00",
        }], {}, now=datetime(2026, 8, 1, 4, 0, tzinfo=UTC),
    )

    assert history[0]["reason"] == "stop_loss"
    assert history[0]["reason_source"] == "price_inference"


def test_closed_position_reason_uses_protection_metadata_when_levels_missing() -> None:
    history = multi_route._build_closed_position_history(
        [{
            "position_id": "tp-1", "symbol": "ETHUSDT", "side": "SHORT",
            "quantity": 1, "entry_price": 100, "close_price": 90,
            "realized_pnl": 10, "closed_at": "2026-08-01T01:00:00+00:00",
        }], {
            "protection:tp-1:take_profit_1": {
                "metadata_kind": "protection_intent",
                "position_id": "tp-1", "role": "take_profit_1",
                "trigger_price": 92,
            },
        }, now=datetime(2026, 8, 1, 4, 0, tzinfo=UTC),
    )

    assert history[0]["reason"] == "take_profit_1"
    assert history[0]["reason_source"] == "price_inference"


def test_closed_loss_never_uses_take_profit_intent_as_reason() -> None:
    history = multi_route._build_closed_position_history(
        [{
            "position_id": "loss-1", "symbol": "BTCUSDT", "side": "LONG",
            "quantity": 1, "entry_price": 100, "close_price": 94,
            "realized_pnl": -6, "closed_at": "2026-08-01T01:00:00+00:00",
        }], {
            "protection:loss-1:take_profit_1": {
                "metadata_kind": "protection_intent",
                "position_id": "loss-1", "role": "take_profit_1",
                "trigger_price": 106,
            },
        }, now=datetime(2026, 8, 1, 4, 0, tzinfo=UTC),
    )

    assert history[0]["reason"] == "exchange_closed_without_bot_reason"


def test_filled_tp_order_has_partial_reason_only_when_profitable() -> None:
    order = multi_route._normalize_bitunix_order(
        {
            "orderId": "tp-filled", "symbol": "BTCUSDT", "side": "SELL",
            "orderType": "LIMIT", "status": "FILLED", "qty": "0.3",
            "tradeQty": "0.3", "dealAvgPrice": "106", "reduceOnly": True,
            "realizedPNL": "1.8",
        },
        {
            "tp-filled": {
                "role": "take_profit_1", "reason": "take_profit_1",
                "position_id": "p1", "metadata_kind": "bot_order",
            }
        },
    )

    assert order["reason"] == "take_profit_1"
    assert order["close_scope"] == "partial"
    assert order["close_label"] == "Partial close — take profit 1"


def test_closed_position_reason_has_exchange_fallback() -> None:
    history = multi_route._build_closed_position_history(
        [{
            "position_id": "manual-1", "symbol": "SOLUSDT", "side": "LONG",
            "quantity": 1, "entry_price": 100, "close_price": 101,
            "realized_pnl": 1, "closed_at": "2026-08-01T01:00:00+00:00",
        }], {}, now=datetime(2026, 8, 1, 4, 0, tzinfo=UTC),
    )

    assert history[0]["reason"] == "exchange_closed_without_bot_reason"
    assert history[0]["reason_source"] == "exchange_lifecycle"


@pytest.mark.parametrize("field", ["realizedPNL", "realizedPnl", "realized_pnl"])
def test_bitunix_closed_position_preserves_positive_realized_pnl(field: str) -> None:
    position = multi_route._normalize_bitunix_closed_position({
        "positionId": "profit-1", "symbol": "FILUSDT", "side": "SHORT",
        field: "1.55", "fee": "0.05", "funding": "0",
        "ctime": 1691382137448, "mtime": 1691385737448,
    })

    assert position["realized_pnl"] == pytest.approx(1.55)
    assert position["net_pnl"] == pytest.approx(1.50)


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
