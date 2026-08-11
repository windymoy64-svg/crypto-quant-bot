from __future__ import annotations

from app.dashboard import services
from app.dashboard.services import dashboard_service
from app.dashboard.routes import multi_portfolio


def test_dashboard_service_market_portfolio_analytics_health_are_valid_objects() -> None:
    market = dashboard_service.market()
    portfolio = dashboard_service.portfolio()
    analytics = dashboard_service.analytics()
    health = dashboard_service.health()

    assert isinstance(market, dict)
    assert isinstance(portfolio, dict)
    assert isinstance(analytics, dict)
    assert isinstance(health, dict)

    assert "signals" in market
    assert "open_positions" in portfolio
    assert "performance" in analytics
    assert health["status"] == "ok"
    assert market["read_only"] is True
    assert portfolio["read_only"] is True
    assert analytics["read_only"] is True
    assert health["read_only"] is True


def test_paper_order_history_only_contains_fully_closed_position(monkeypatch) -> None:
    events = [
        {
            "type": "partial_close",
            "symbol": "BTC/USDT",
            "reason": "take_profit_1",
            "price": 110.0,
            "timestamp": "2026-07-28T01:00:00+00:00",
            "position": {
                "side": "BUY",
                "entry": 100.0,
                "size": 1.0,
                "partial_size_closed": 0.3,
                "partial_realized_pnl": 3.0,
            },
        },
        {
            "type": "closed",
            "symbol": "BTC/USDT",
            "reason": "trailing_stop",
            "price": 108.0,
            "timestamp": "2026-07-28T02:00:00+00:00",
            "close_scope": "full",
            "close_label": "Full close — trailing stop",
            "position": {
                "side": "BUY",
                "entry": 100.0,
                "size": 1.0,
                "final_size_closed": 0.7,
                "realized_pnl": 8.6,
            },
        },
    ]
    monkeypatch.setattr(services, "read_jsonl_file", lambda *_args, **_kwargs: events)

    history = dashboard_service._paper_order_history()

    assert len(history) == 1
    assert history[0]["status"] == "CLOSED"
    assert history[0]["close_scope"] == "full"
    assert history[0]["reason"] == "trailing_stop"
    assert history[0]["close_reason"] == "trailing_stop"
    assert history[0]["close_label"] == "Full close — trailing stop"
    assert history[0]["price"] == 100.0
    assert history[0]["quantity"] == 1.0


def test_dashboard_trailing_active_uses_current_status_not_stale_flag(monkeypatch) -> None:
    from types import SimpleNamespace

    state = SimpleNamespace(
        trailing_active=True,
        trailing_status="inactive",
        current_stop=0.1925,
        trailing_candidate_stop=None,
        trailing_percent=None,
    )

    class FakeStore:
        def load(self):
            return {"ada": state}

    monkeypatch.setattr(multi_portfolio, "LiveLifecycleStore", FakeStore, raising=False)
    # The route imports the store lazily, so patch the execution module used by
    # that import path instead of relying on a production file.
    import app.execution.live_lifecycle as lifecycle
    monkeypatch.setattr(lifecycle, "LiveLifecycleStore", FakeStore)

    positions = [{"position_id": "ada", "symbol": "ADAUSDT"}]
    multi_portfolio._attach_live_trailing_status(positions)

    assert positions[0]["trailing_active"] is False
    assert positions[0]["trailing_stop_loss"] is None
