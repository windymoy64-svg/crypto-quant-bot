from __future__ import annotations

import argparse
import json
import signal
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from app.market.scanner import scan_symbol_rankings
from app.paper.realtime_engine import PaperTradingConfig, RealtimePaperTradingEngine
from app.execution.live_executor import LiveExecutor, LiveTradingSettings
from app.config.production import production_shutdown, production_startup
from app.logger import setup_production_logging

def load_json(path: str) -> dict[str, object]:
    with Path(path).open(encoding="utf-8-sig") as file:
        data = json.load(file)

    if not isinstance(data, dict):
        raise TypeError(f"JSON root must be an object: {path}")

    return data

def read_json_file(
    path: Path,
    default: object,
) -> object:
    if not path.exists():
        return default

    try:
        return json.loads(
            path.read_text(encoding="utf-8-sig")
        )
    except (OSError, json.JSONDecodeError):
        return default

def write_scan_outputs(
    results: list[dict[str, object]],
    short_results: list[dict[str, object]],
    latest_output: str,
    history_output: str,
    paper: dict[str, object] | None = None,
) -> None:
    now = datetime.now(tz=UTC).isoformat()
    payload = {
        "timestamp": now,
        "signals": results,
        "short_signals": short_results,
    }
    if paper is not None:
        payload["paper"] = paper

    latest_path = Path(latest_output)
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    latest_path.write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )

    history_path = Path(history_output)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    with history_path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload) + "\n")

def prepare_confirmed_short_signals(
    long_results: list[dict[str, object]],
    short_results: list[dict[str, object]],
    config: dict[str, object],
) -> list[dict[str, object]]:
    """Ubah kandidat shadow SHORT menjadi input paper setelah konfirmasi."""

    if not bool(config.get("short_execution_enabled", False)):
        return []

    required_cycles = max(
        1,
        int(config.get("short_confirmation_cycles", 2)),
    )
    minimum_edge = float(
        config.get("minimum_direction_edge", 5.0)
    )
    state_path = Path(
        str(
            config.get(
                "short_confirmation_state_path",
                "logs/short_confirmation_state.json",
            )
        )
    )

    previous = read_json_file(state_path, {})
    if not isinstance(previous, dict):
        previous = {}

    counters = previous.get("counters", {})
    if not isinstance(counters, dict):
        counters = {}

    long_by_symbol = {
        str(item.get("symbol")): item
        for item in long_results
    }

    current_sell_symbols: set[str] = set()
    confirmed: list[dict[str, object]] = []

    for item in short_results:
        symbol = str(item.get("symbol"))
        short_action = str(
            item.get("short_action", "")
        ).upper()

        if short_action != "SELL":
            continue

        short_confidence = float(
            item.get("short_confidence") or 0.0
        )
        long_confidence = float(
            long_by_symbol.get(symbol, {}).get("confidence")
            or 0.0
        )
        direction_edge = (
            short_confidence - long_confidence
        )

        failed_gates = item.get(
            "short_failed_gates",
            [],
        )
        if (
            not isinstance(failed_gates, list)
            or failed_gates
            or direction_edge < minimum_edge
        ):
            continue

        entry = float(item.get("short_entry") or 0.0)
        stop_loss = float(
            item.get("short_stop_loss") or 0.0
        )
        take_profit = item.get(
            "short_take_profit",
            [],
        )

        valid_levels = (
            entry > 0
            and stop_loss > entry
            and isinstance(take_profit, list)
            and len(take_profit) == 3
            and entry
            > float(take_profit[0])
            > float(take_profit[1])
            > float(take_profit[2])
            > 0
        )
        if not valid_levels:
            continue

        current_sell_symbols.add(symbol)
        count = min(
            required_cycles,
            int(counters.get(symbol, 0)) + 1,
        )
        counters[symbol] = count

        if count < required_cycles:
            continue

        confirmed.append(
            {
                "symbol": symbol,
                "action": "SELL",
                "confidence": short_confidence,
                "score": float(
                    item.get("short_score") or 0.0
                ),
                "entry": entry,
                "stop_loss": stop_loss,
                "take_profit": [
                    float(value)
                    for value in take_profit
                ],
                "risk": item.get("risk", "HIGH"),
                "risk_reward": float(
                    item.get("short_risk_reward") or 0.0
                ),
                "strategy": "Weighted Bearish Rule Engine",
                "failed_gates": [],
                "direction_edge": round(
                    direction_edge,
                    2,
                ),
                "confirmation_cycles": count,
            }
        )

    counters = {
        symbol: count
        for symbol, count in counters.items()
        if symbol in current_sell_symbols
    }

    state_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    state_path.write_text(
        json.dumps(
            {
                "updated_at": datetime.now(
                    tz=UTC
                ).isoformat(),
                "required_cycles": required_cycles,
                "minimum_direction_edge": minimum_edge,
                "counters": counters,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    return confirmed

def prepare_confirmed_short_signals(
    long_results: list[dict[str, object]],
    short_results: list[dict[str, object]],
    config: dict[str, object],
) -> list[dict[str, object]]:
    """Ubah kandidat shadow SHORT menjadi input paper setelah konfirmasi."""

    if not bool(config.get("short_execution_enabled", False)):
        return []

    required_cycles = max(
        1,
        int(config.get("short_confirmation_cycles", 2)),
    )
    minimum_edge = float(
        config.get("minimum_direction_edge", 5.0)
    )
    state_path = Path(
        str(
            config.get(
                "short_confirmation_state_path",
                "logs/short_confirmation_state.json",
            )
        )
    )

    previous = read_json_file(state_path, {})
    if not isinstance(previous, dict):
        previous = {}

    counters = previous.get("counters", {})
    if not isinstance(counters, dict):
        counters = {}

    long_by_symbol = {
        str(item.get("symbol")): item
        for item in long_results
    }

    current_sell_symbols: set[str] = set()
    confirmed: list[dict[str, object]] = []

    for item in short_results:
        symbol = str(item.get("symbol"))
        short_action = str(
            item.get("short_action", "")
        ).upper()

        if short_action != "SELL":
            continue

        short_confidence = float(
            item.get("short_confidence") or 0.0
        )
        long_confidence = float(
            long_by_symbol.get(symbol, {}).get("confidence")
            or 0.0
        )
        direction_edge = (
            short_confidence - long_confidence
        )

        failed_gates = item.get(
            "short_failed_gates",
            [],
        )
        if (
            not isinstance(failed_gates, list)
            or failed_gates
            or direction_edge < minimum_edge
        ):
            continue

        entry = float(item.get("short_entry") or 0.0)
        stop_loss = float(
            item.get("short_stop_loss") or 0.0
        )
        take_profit = item.get(
            "short_take_profit",
            [],
        )

        valid_levels = (
            entry > 0
            and stop_loss > entry
            and isinstance(take_profit, list)
            and len(take_profit) == 3
            and entry
            > float(take_profit[0])
            > float(take_profit[1])
            > float(take_profit[2])
            > 0
        )
        if not valid_levels:
            continue

        current_sell_symbols.add(symbol)
        count = int(counters.get(symbol, 0)) + 1
        counters[symbol] = count

        if count < required_cycles:
            continue

        confirmed.append(
            {
                "symbol": symbol,
                "action": "SELL",
                "confidence": short_confidence,
                "score": float(
                    item.get("short_score") or 0.0
                ),
                "entry": entry,
                "stop_loss": stop_loss,
                "take_profit": [
                    float(value)
                    for value in take_profit
                ],
                "risk": item.get("risk", "HIGH"),
                "risk_reward": float(
                    item.get("short_risk_reward") or 0.0
                ),
                "strategy": "Weighted Bearish Rule Engine",
                "failed_gates": [],
                "direction_edge": round(
                    direction_edge,
                    2,
                ),
                "confirmation_cycles": count,
            }
        )

    counters = {
        symbol: count
        for symbol, count in counters.items()
        if symbol in current_sell_symbols
    }

    state_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    state_path.write_text(
        json.dumps(
            {
                "updated_at": datetime.now(
                    tz=UTC
                ).isoformat(),
                "required_cycles": required_cycles,
                "minimum_direction_edge": minimum_edge,
                "counters": counters,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    return confirmed

def run_once(runtime_config: dict[str, object]) -> dict[str, object]:
    scan_config_path = str(runtime_config.get("scan_config", "configs/market_scan.json"))
    paper_config_path = str(runtime_config.get("paper_config", "configs/paper_trading.json"))
    live_config_path = str(runtime_config.get("live_config", "configs/live_trading.json"))
    latest_output = str(runtime_config.get("latest_output", "logs/latest_signals.json"))
    history_output = str(runtime_config.get("history_output", "logs/signals.jsonl"))

    scan_config = load_json(scan_config_path)
    rankings = scan_symbol_rankings(scan_config)

    # Hanya LONG yang dikirim ke paper/live executor.
    results = [item.to_dict() for item in rankings.long]

    # SHORT masih shadow; hanya ditulis ke output.
    short_results = [
        item.to_dict()
        for item in rankings.short
    ]

    confirmed_short_results = (
        prepare_confirmed_short_signals(
            results,
            short_results,
            scan_config,
        )
    )
    for item in [*results, *short_results]:
        if item.get("data_source") == "sample":
            raise RuntimeError(
                f"Data {item['symbol']} masih sample — koneksi Binance gagal, "
                "bukan data real. Periksa jaringan/rate limit."
            )

    paper: dict[str, object] | None = None
    if bool(runtime_config.get("paper_trading_enabled", True)):
        paper_config = PaperTradingConfig.from_dict(load_json(paper_config_path))
        paper_signals = [
            *results,
            *confirmed_short_results,
        ]

        paper_signals = [
            *results,
            *confirmed_short_results,
        ]

        paper = RealtimePaperTradingEngine(
            paper_config
        ).process_signals(paper_signals)

    live_decisions: list[dict[str, object]] = []
    if bool(runtime_config.get("live_execution_enabled", False)):
        live_settings = LiveTradingSettings.from_dict(load_json(live_config_path))
        live_executor = LiveExecutor(live_settings)
        live_decisions = [live_executor.evaluate_signal(signal) for signal in results]

    write_scan_outputs(
        results,
        short_results,
        latest_output,
        history_output,
        paper=paper,
    )
    return {
        "latest_output": latest_output,
        "history_output": history_output,
        "signals": results,
        "short_signals": short_results,
        "confirmed_short_signals": confirmed_short_results,
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
        short_summary = [
            (
                f"{item['symbol']}="
                f"{item.get('short_action')}("
                f"{item.get('short_confidence')})"
            )
            for item in result.get("short_signals", [])[:5]
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
            f"{datetime.now(tz=UTC).isoformat()} | "
            + ", ".join(summary)
            + paper_summary
            + live_summary
            + (
                " | short shadow top="
                + ", ".join(short_summary)
                if short_summary
                else ""
            ),
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
