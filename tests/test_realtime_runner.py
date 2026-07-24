import json
from pathlib import Path
from unittest.mock import Mock, patch

from run_realtime import (
    load_open_position_symbols,
    prepare_paper_signals,
    release_unused_memory,
    write_scan_outputs,
)


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
