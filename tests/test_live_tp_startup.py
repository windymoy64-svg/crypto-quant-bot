from __future__ import annotations

from types import SimpleNamespace

import run_realtime


def test_startup_reconciles_unprotected_live_bitunix_position(monkeypatch) -> None:
    calls: list[list[dict[str, object]]] = []

    monkeypatch.setattr(run_realtime, "load_execution_preferences", lambda: SimpleNamespace(
        mode="live", network_enabled=True, live_confirmed=True,
    ))
    monkeypatch.setattr(run_realtime, "load_portfolio_preferences", lambda: SimpleNamespace(
        active_execution_exchange="bitunix",
    ))
    monkeypatch.setattr(run_realtime, "load_exchange_credentials", lambda **_kwargs: SimpleNamespace(
        api_key="key", api_secret="secret", is_configured=True,
    ))
    from app.dashboard.routes import multi_portfolio
    monkeypatch.setattr(multi_portfolio, "_load_bitunix_details", lambda *_args: {
        "positions": [
            {"position_id": "p1", "symbol": "SUIUSDT", "side": "SELL", "take_profit": None},
            {"position_id": "p2", "symbol": "ETHUSDT", "side": "SELL", "take_profit": "1800"},
        ],
    })

    class Adapter:
        def __init__(self, *_args, **_kwargs):
            pass

        def reconcile_take_profits(self, positions, *, timestamp):
            calls.append(positions)
            return []

    monkeypatch.setattr(run_realtime, "BitunixFuturesExecutorAdapter", Adapter)

    run_realtime.reconcile_live_take_profits_at_startup({
        "agent_pipeline": {"enabled": True, "allow_live_orders": True},
    })

    assert [[position["position_id"] for position in rows] for rows in calls] == [["p1", "p2"]]