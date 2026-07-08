from pathlib import Path

from run_realtime import write_scan_outputs


def test_write_scan_outputs_creates_latest_and_history(tmp_path: Path) -> None:
    latest = tmp_path / "latest.json"
    history = tmp_path / "history.jsonl"
    results = [{"symbol": "BTC/USDT", "action": "SKIP"}]

    write_scan_outputs(results, str(latest), str(history), paper={"balance": 10000})

    assert latest.exists()
    assert history.exists()
    assert "BTC/USDT" in latest.read_text(encoding="utf-8")
    assert "balance" in latest.read_text(encoding="utf-8")
    assert "BTC/USDT" in history.read_text(encoding="utf-8")
