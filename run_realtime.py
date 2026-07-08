from __future__ import annotations

import argparse
import json
import signal
import time
from datetime import UTC, datetime
from pathlib import Path

from app.market.scanner import scan_symbols
from app.paper.realtime_engine import PaperTradingConfig, RealtimePaperTradingEngine
from app.execution.live_executor import LiveExecutor, LiveTradingSettings
from app.config.production import production_shutdown, production_startup
from app.logger import setup_production_logging


def load_json(path: str) -> dict[str, object]:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_scan_outputs(
    results: list[dict[str, object]],
    latest_output: str,
    history_output: str,
    paper: dict[str, object] | None = None,
) -> None:
    now = datetime.now(tz=UTC).isoformat()
    payload = {
        "timestamp": now,
        "signals": results,
    }
    if paper is not None:
        payload["paper"] = paper

    latest_path = Path(latest_output)
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    latest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    history_path = Path(history_output)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    with history_path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload) + "\n")


def run_once(runtime_config: dict[str, object]) -> dict[str, object]:
    scan_config_path = str(runtime_config.get("scan_config", "configs/market_scan.json"))
    paper_config_path = str(runtime_config.get("paper_config", "configs/paper_trading.json"))
    live_config_path = str(runtime_config.get("live_config", "configs/live_trading.json"))
    latest_output = str(runtime_config.get("latest_output", "logs/latest_signals.json"))
    history_output = str(runtime_config.get("history_output", "logs/signals.jsonl"))

    scan_config = load_json(scan_config_path)
    scan_items = scan_symbols(scan_config)
    results = [item.to_dict() for item in scan_items]

    paper: dict[str, object] | None = None
    if bool(runtime_config.get("paper_trading_enabled", True)):
        paper_config = PaperTradingConfig.from_dict(load_json(paper_config_path))
        paper = RealtimePaperTradingEngine(paper_config).process_signals(results)

    live_decisions: list[dict[str, object]] = []
    if bool(runtime_config.get("live_execution_enabled", False)):
        live_settings = LiveTradingSettings.from_dict(load_json(live_config_path))
        live_executor = LiveExecutor(live_settings)
        live_decisions = [live_executor.evaluate_signal(signal) for signal in results]

    write_scan_outputs(results, latest_output, history_output, paper=paper)
    return {
        "latest_output": latest_output,
        "history_output": history_output,
        "signals": results,
        "paper": paper,
        "live_decisions": live_decisions,
    }


def main() -> None:
    setup_production_logging()
    production_startup()
    parser = argparse.ArgumentParser(description="Run realtime crypto market scanner")
    parser.add_argument("--config", default="configs/realtime.json")
    parser.add_argument("--once", action="store_true", help="Run one scan and exit")
    args = parser.parse_args()

    runtime_config = load_json(args.config)
    interval_seconds = int(runtime_config.get("interval_seconds", 60))
    stop_requested = False

    def request_stop(signum: int, frame: object) -> None:
        nonlocal stop_requested
        stop_requested = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    while not stop_requested:
        result = run_once(runtime_config)
        summary = [
            f"{item['symbol']}={item['action']}({item['confidence']})/{item['data_source']}"
            for item in result["signals"]
        ]
        paper_summary = ""
        if result.get("paper"):
            paper = result["paper"]
            paper_summary = (
                f" | paper balance={paper['balance']} "
                f"open={len(paper['open_positions'])} events={len(paper['events'])}"
            )
        live_summary = ""
        if result.get("live_decisions"):
            live_summary = f" | live decisions={len(result['live_decisions'])}"
        print(
            f"{datetime.now(tz=UTC).isoformat()} | " + ", ".join(summary) + paper_summary + live_summary,
            flush=True,
        )

        if args.once:
            break
        for _ in range(interval_seconds):
            if stop_requested:
                break
            time.sleep(1)

    production_shutdown()


if __name__ == "__main__":
    main()
