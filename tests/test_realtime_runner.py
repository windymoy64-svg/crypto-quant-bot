import json
from pathlib import Path

from run_realtime import (
    load_open_position_symbols,
    prepare_paper_signals,
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
