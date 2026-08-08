import json
from pathlib import Path
from unittest.mock import Mock, patch

from run_realtime import (
    build_runtime_agent_coordinator,
    load_open_position_symbols,
    prepare_paper_signals,
    release_unused_memory,
    write_scan_outputs,
)


def test_runtime_coordinator_uses_binance_futures_adapter_for_live(monkeypatch) -> None:
    from app.agent_pipeline.bridge import AgentPipelineRuntimeConfig
    from app.settings.execution_preferences import ExecutionPreferences
    from app.settings.exchange_credentials import ExchangeCredentialsRecord

    config = AgentPipelineRuntimeConfig(enabled=True, execute_decisions=True, allow_live_orders=True)
    credentials = ExchangeCredentialsRecord(
        exchange="binance", api_key="key", api_secret="secret", testnet=True, updated_at=None,
    )
    monkeypatch.setattr("run_realtime.load_execution_preferences", lambda: ExecutionPreferences("live", True))
    monkeypatch.setattr("run_realtime.load_exchange_credentials", lambda exchange: credentials)
    monkeypatch.setattr("run_realtime.FuturesHttpClient", lambda *args, **kwargs: object())
    monkeypatch.setattr("app.executor_agent.binance_futures_adapter.FuturesAccountReader", lambda client: type("Reader", (), {"balances": lambda self: []})())
    coordinator = build_runtime_agent_coordinator(config=config, exchange="binance")

    assert coordinator.executor_agent.live is True
    assert coordinator.executor_agent.paper_parity_verified is True
    assert coordinator.executor_agent._exchange.__class__.__name__ == "BinanceFuturesExecutorAdapter"


def test_runtime_coordinator_uses_same_executor_brain_in_dry_run(monkeypatch) -> None:
    from app.agent_pipeline.bridge import AgentPipelineRuntimeConfig
    from app.settings.execution_preferences import ExecutionPreferences

    config = AgentPipelineRuntimeConfig(enabled=True, execute_decisions=True, allow_live_orders=True)
    monkeypatch.setattr("run_realtime.load_execution_preferences", lambda: ExecutionPreferences("dry_run", False))
    coordinator = build_runtime_agent_coordinator(config=config, exchange="binance")

    assert coordinator.executor_agent.live is False


def test_write_scan_outputs_creates_latest_and_history(tmp_path: Path) -> None:
    latest = tmp_path / "latest.json"
    history = tmp_path / "history.jsonl"
    results = [{"symbol": "BTC/USDT", "action": "SKIP"}]

    write_scan_outputs(
        results,
        [],
        str(latest),
        str(history),
        paper={"balance": 10000},
    )

    assert latest.exists()
    assert history.exists()
    assert "BTC/USDT" in latest.read_text(encoding="utf-8")
    assert "balance" in latest.read_text(encoding="utf-8")
    assert "BTC/USDT" in history.read_text(encoding="utf-8")


def test_load_open_position_symbols_supports_position_map(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "paper_state.json"
    state_path.write_text(
        json.dumps(
            {
                "open_positions": {
                    "ALLO/USDT": {"last_price": 0.37},
                    "THETA-USDT": {"last_price": 0.15},
                }
            }
        ),
        encoding="utf-8",
    )

    symbols = load_open_position_symbols(str(state_path))

    assert symbols == ["ALLO/USDT", "THETA/USDT"]


def test_load_open_position_symbols_includes_pending_orders(tmp_path: Path) -> None:
    state_path = tmp_path / "paper_state.json"
    state_path.write_text(json.dumps({
        "open_positions": {"BTC/USDT": {}},
        "pending_orders": {
            "PROM/USDT": {"status": "PENDING"},
            "BTC/USDT": {"status": "PENDING"},
        },
    }), encoding="utf-8")

    assert load_open_position_symbols(str(state_path)) == [
        "BTC/USDT", "PROM/USDT",
    ]


def test_prepare_paper_signals_keeps_unranked_open_position_tick() -> None:
    ranked = [
        {"symbol": "BTC/USDT", "action": "BUY", "entry": 100.0}
    ]
    tracked = [
        {"symbol": "ALLO/USDT", "action": "BUY", "entry": 0.38}
    ]

    signals = prepare_paper_signals(
        ranked,
        tracked,
        ["ALLO/USDT"],
    )

    assert [item["symbol"] for item in signals] == [
        "BTC/USDT",
        "ALLO/USDT",
    ]
    assert signals[1]["entry"] == 0.38
    assert signals[1]["action"] == "SKIP"
    assert signals[1]["tracking_reason"] == "open_position"


def test_run_once_reuses_market_data_service_cache(tmp_path: Path) -> None:
    scan_config = tmp_path / "scan.json"
    scan_config.write_text(
        json.dumps({"exchange": "binance", "fallback_to_sample_data": False}),
        encoding="utf-8",
    )
    runtime_config = {
        "scan_config": str(scan_config),
        "paper_trading_enabled": False,
        "live_execution_enabled": False,
        "latest_output": str(tmp_path / "latest.json"),
        "history_output": str(tmp_path / "history.jsonl"),
    }
    rankings = Mock(long=[], short=[], tracked=[], market_breadth={}, move_alerts=[])
    cache: dict = {}

    with patch("run_realtime.MarketDataService") as service_type, patch(
        "run_realtime.scan_symbol_rankings",
        return_value=rankings,
    ) as scan:
        service = service_type.return_value
        from run_realtime import run_once

        run_once(runtime_config, market_data_cache=cache)
        run_once(runtime_config, market_data_cache=cache)

    service_type.assert_called_once_with(
        exchange="binance",
        fallback_to_sample_data=False,
    )
    assert scan.call_count == 2
    assert all(call.kwargs["market_data"] is service for call in scan.call_args_list)


def test_release_unused_memory_is_safe() -> None:
    release_unused_memory()
