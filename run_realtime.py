from __future__ import annotations

import argparse
import gc
import json
import signal
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from app.market.scanner import scan_symbol_rankings
from app.market.data_service import MarketDataService
from app.paper.realtime_engine import PaperTradingConfig, RealtimePaperTradingEngine
from app.execution.live_executor import LiveExecutor, LiveTradingSettings
from app.config.production import production_shutdown, production_startup
from app.logger import setup_production_logging
from app.strategies.acr_realtime_enrichment import (
    ACREnrichmentConfig,
    enrich_realtime_signals,
)
from app.settings.trading_preferences import load_trading_preferences
from app.settings.portfolio_preferences import load_portfolio_preferences
from app.settings.execution_preferences import load_execution_preferences
from app.settings.exchange_credentials import load_exchange_credentials
from app.agent_pipeline.coordinator import AgentPipelineConfig, AgentPipelineCoordinator
from app.executor_agent.agent import ExecutorAgent
from app.executor_agent.bitunix_futures_adapter import (
    BitunixCredentials,
    BitunixFuturesExecutorAdapter,
    BitunixLiveSafetyGate,
)
from app.agent_pipeline.bridge import (
    AgentPipelineRuntimeConfig,
    run_pipeline_bridge,
)
from app.config.strategy_version import compute_strategy_version
from app.risk.entry_guards import (
    ClosedCandleGuard,
    EntryGuardConfig,
    LiquiditySpreadGate,
    RegimeGate,
)
from app.risk.portfolio_heat import OpenPositionRisk, PortfolioHeatGuard
from app.learning_agent.runtime import (
    LearningRecorderConfig,
    build_recorder_if_enabled,
)


def release_unused_memory() -> None:
    """Best-effort: kembalikan heap siklus scan yang sudah bebas ke OS.

    CPython/glibc sering mempertahankan arena dari parsing response exchange
    meski semua object sudah tidak direferensikan. ``malloc_trim`` hanya
    melepas halaman heap yang memang kosong; object aktif tidak disentuh.
    Runtime non-glibc tetap aman karena kegagalan diabaikan.
    """

    gc.collect()
    try:
        import ctypes

        libc = ctypes.CDLL(None)
        malloc_trim = getattr(libc, "malloc_trim", None)
        if malloc_trim is not None:
            malloc_trim.argtypes = [ctypes.c_size_t]
            malloc_trim.restype = ctypes.c_int
            malloc_trim(0)
    except (AttributeError, OSError):
        pass

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


def load_open_position_symbols(state_path: str) -> list[str]:
    """Ambil simbol posisi terbuka yang wajib terus dipantau harganya."""

    state = read_json_file(Path(state_path), {})
    if not isinstance(state, dict):
        return []

    positions = state.get("open_positions", {})
    if isinstance(positions, dict):
        raw_symbols = positions.keys()
    elif isinstance(positions, list):
        raw_symbols = (
            item.get("symbol")
            for item in positions
            if isinstance(item, dict)
        )
    else:
        return []

    seen: set[str] = set()
    symbols: list[str] = []
    for value in raw_symbols:
        symbol = str(value or "").strip().upper().replace("-", "/")
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        symbols.append(symbol)
    return symbols


def prepare_paper_signals(
    entry_signals: list[dict[str, object]],
    tracked_signals: list[dict[str, object]],
    open_position_symbols: list[str],
) -> list[dict[str, object]]:
    """Gabungkan kandidat entry dan tick posisi tanpa simbol duplikat.

    Sinyal untuk posisi yang sudah terbuka dipaksa menjadi SKIP. Harga tetap
    diproses untuk PnL/SL/TP/trailing stop, tetapi posisi yang tertutup pada
    siklus yang sama tidak langsung dibuka ulang oleh sinyal entry lama.
    """

    open_symbols = set(open_position_symbols)
    prepared: list[dict[str, object]] = []
    seen: set[str] = set()

    for source in [*entry_signals, *tracked_signals]:
        symbol = str(source.get("symbol", ""))
        if not symbol or symbol in seen:
            continue

        signal_item = dict(source)
        if symbol in open_symbols:
            signal_item["action"] = "SKIP"
            signal_item["tracking_reason"] = "open_position"

        prepared.append(signal_item)
        seen.add(symbol)

    return prepared


def stamp_strategy_version(
    signals: list[dict[str, object]],
    version: dict[str, object],
) -> None:
    """Attach strategy version to every directional signal for attribution."""
    for item in signals:
        meta = item.get("meta")
        if not isinstance(meta, dict):
            meta = {}
            item["meta"] = meta
        meta["strategy_version"] = version


def apply_entry_guards(
    signals: list[dict[str, object]],
    *,
    guard_config: EntryGuardConfig,
    market_data: MarketDataService,
    paper_state: dict[str, object] | None,
    equity: float,
) -> list[dict[str, object]]:
    """Apply closed-candle, regime, and liquidity guards to directional entries.

    Non-directional and tracked-position signals pass through untouched. A vetoed
    entry is downgraded to ``SKIP`` with ``entry_guard_veto`` so the paper engine
    never opens it, while the agent pipeline still sees the row for auditability.
    """
    if not guard_config.enabled:
        return signals

    closed_candle = ClosedCandleGuard(guard_config.closed_candle_tolerance_seconds)
    regime_gate = RegimeGate(
        guard_config.reject_regimes,
        guard_config.short_observation_regimes,
    )
    liquidity_gate = LiquiditySpreadGate(
        min_quote_volume_usd=guard_config.min_quote_volume_usd,
        max_spread_percent_of_stop=guard_config.max_spread_percent_of_stop,
        max_round_trip_cost_percent=guard_config.max_round_trip_cost_percent,
        taker_fee_rate=guard_config.taker_fee_rate,
        slippage_basis_points=guard_config.slippage_basis_points,
    )
    heat_guard = PortfolioHeatGuard()
    now = datetime.now(tz=UTC)

    open_positions: list[OpenPositionRisk] = []
    if isinstance(paper_state, dict):
        positions = paper_state.get("open_positions")
        pos_iter = (
            positions.values() if isinstance(positions, dict)
            else positions if isinstance(positions, list)
            else []
        )
        for pos in pos_iter:
            if not isinstance(pos, dict):
                continue
            risk_amount = abs(
                float(pos.get("entry", 0.0)) - float(pos.get("static_stop_loss", 0.0))
            ) * float(pos.get("remaining_size") or pos.get("size") or 0.0)
            open_positions.append(
                OpenPositionRisk(
                    symbol=str(pos.get("symbol", "")),
                    side=str(pos.get("side", "")),
                    risk_amount=risk_amount,
                )
            )

    guarded: list[dict[str, object]] = []
    for signal in signals:
        action = str(signal.get("action", "")).upper()
        if action not in {"BUY", "SELL"}:
            guarded.append(signal)
            continue

        symbol = str(signal.get("symbol", ""))
        meta = signal.get("meta")
        if not isinstance(meta, dict):
            meta = {}
            signal["meta"] = meta
        tf = str(signal.get("entry_timeframe") or meta.get("entry_timeframe") or "15m")
        candle_ts = meta.get("last_candle_timestamp")
        regime = str(meta.get("regime") or meta.get("acr_confirmation", {}).get("acr_decision", {}).get("regime") or "MIXED")

        vetoed = False
        veto_reason = ""

        candle_result = closed_candle.validate(
            last_candle_timestamp=candle_ts, now=now, timeframe=tf,
        )
        if not candle_result.valid:
            vetoed, veto_reason = True, candle_result.reason

        if not vetoed:
            regime_result = regime_gate.validate(action=action, regime=regime)
            if not regime_result.valid:
                vetoed, veto_reason = True, regime_result.reason

        if not vetoed:
            risk_amount = equity * (0.5 / 100.0)
            heat_result = heat_guard.validate(
                equity=equity,
                open_positions=open_positions,
                candidate=OpenPositionRisk(
                    symbol=symbol, side=action, risk_amount=risk_amount,
                ),
            )
            if not heat_result.valid:
                vetoed, veto_reason = True, heat_result.reason

        meta["entry_guards"] = {
            "candle": candle_result.to_dict(),
            "regime": regime_result.to_dict() if not vetoed else {},
            "portfolio_heat": heat_result.to_dict() if not vetoed else {},
        }
        if vetoed:
            signal = dict(signal)
            signal["action"] = "SKIP"
            signal["tracking_reason"] = "entry_guard_veto"
            signal["veto_reason"] = veto_reason
        guarded.append(signal)
    return guarded


def build_runtime_agent_coordinator(
    *, config: AgentPipelineRuntimeConfig, exchange: str,
) -> AgentPipelineCoordinator:
    """Build the selected exchange executor from persisted operator mode."""

    execution = load_execution_preferences()
    coordinator_config = AgentPipelineConfig(
        min_scanner_confidence=config.min_scanner_confidence,
        execute_decisions=config.execute_decisions,
    )
    if execution.mode == "paper":
        return AgentPipelineCoordinator(
            executor_agent=ExecutorAgent(), config=coordinator_config,
        )

    credentials = load_exchange_credentials(exchange=exchange)
    if credentials is None or not credentials.is_configured:
        return AgentPipelineCoordinator(
            executor_agent=ExecutorAgent(live=True), config=coordinator_config,
        )

    if exchange != "bitunix":
        # Binance live wiring remains fail-closed until the selected futures
        # account config and endpoint are built through the same runtime path.
        return AgentPipelineCoordinator(
            executor_agent=ExecutorAgent(live=True), config=coordinator_config,
        )

    network_enabled = execution.network_enabled
    adapter = BitunixFuturesExecutorAdapter(
        BitunixCredentials(credentials.api_key, credentials.api_secret),
        safety_gate=BitunixLiveSafetyGate(
            enabled=True,
            dry_run=not network_enabled,
            confirm_live=execution.live_confirmed,
        ),
    )
    balance = 10_000.0
    if network_enabled:
        balance = adapter.available_balance("USDT")
    try:
        trading = load_trading_preferences(exchange=exchange)
        leverage = trading.leverage or 1
    except Exception:
        leverage = 1
    return AgentPipelineCoordinator(
        executor_agent=ExecutorAgent(
            balance=balance,
            leverage=leverage,
            live=True,
            exchange_adapter=adapter,
        ),
        config=coordinator_config,
    )

def write_scan_outputs(
    results: list[dict[str, object]],
    short_results: list[dict[str, object]],
    latest_output: str,
    history_output: str,
    paper: dict[str, object] | None = None,
    tracked_results: list[dict[str, object]] | None = None,
) -> None:
    now = datetime.now(tz=UTC).isoformat()
    payload = {
        "timestamp": now,
        "signals": results,
        "short_signals": short_results,
        # Simbol posisi terbuka yang keluar dari top N tetap dikirim ke
        # dashboard agar harganya ikut realtime setiap siklus scan.
        "tracked_signals": tracked_results or [],
    }
    if paper is not None:
        payload["paper"] = paper


    latest_path = Path(latest_output)
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    # json.dump menulis bertahap sehingga payload scan tidak diduplikasi menjadi
    # satu string besar tambahan di RAM sebelum ditulis.
    with latest_path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2)

    history_path = Path(history_output)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    with history_path.open("a", encoding="utf-8") as file:
        json.dump(payload, file, separators=(",", ":"))
        file.write("\n")

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

def run_once(
    runtime_config: dict[str, object],
    market_data_cache: dict[tuple[str, bool], MarketDataService] | None = None,
) -> dict[str, object]:
    scan_config_path = str(runtime_config.get("scan_config", "configs/market_scan.json"))
    paper_config_path = str(runtime_config.get("paper_config", "configs/paper_trading.json"))
    live_config_path = str(runtime_config.get("live_config", "configs/live_trading.json"))
    latest_output = str(runtime_config.get("latest_output", "logs/latest_signals.json"))
    history_output = str(runtime_config.get("history_output", "logs/signals.jsonl"))

    scan_config = load_json(scan_config_path)
    exchange = str(scan_config.get("exchange", "binance"))
    if bool(runtime_config.get("use_primary_exchange", False)):
        try:
            portfolio_preferences = load_portfolio_preferences()
            exchange = portfolio_preferences.active_execution_exchange
            scan_config = {**scan_config, "exchange": exchange}
        except Exception:
            pass
    fallback = bool(scan_config.get("fallback_to_sample_data", True))
    market_data_key = (exchange.lower(), fallback)
    if market_data_cache is None:
        market_data = MarketDataService(
            exchange=exchange,
            fallback_to_sample_data=fallback,
        )
    else:
        market_data = market_data_cache.get(market_data_key)
        if market_data is None:
            # Konfigurasi exchange jarang berubah. Simpan hanya service aktif
            # agar metadata ccxt lama tidak tertahan setelah hot reload config.
            market_data_cache.clear()
            market_data = MarketDataService(
                exchange=exchange,
                fallback_to_sample_data=fallback,
            )
            market_data_cache[market_data_key] = market_data

    execution_preferences = load_execution_preferences()
    paper_enabled = bool(runtime_config.get("paper_trading_enabled", True)) and (
        execution_preferences.mode == "paper"
    )
    paper_config: PaperTradingConfig | None = None
    open_position_symbols: list[str] = []
    telegram_notifier = None
    if paper_enabled:
        paper_data = load_json(paper_config_path)
        selected_exchange = exchange.lower()
        try:
            preferences = load_trading_preferences(exchange=selected_exchange)
        except Exception:
            preferences = None
        if preferences is not None:
            paper_data = {
                **paper_data,
                "take_profit_percent": preferences.take_profit_percent,
                "stop_loss_percent": preferences.stop_loss_percent,
                "trailing_stop_percent": preferences.trailing_stop_percent,
                "leverage": preferences.leverage,
            }
        paper_config = PaperTradingConfig.from_dict(
            paper_data
        )
        open_position_symbols = load_open_position_symbols(
            paper_config.state_path
        )
        
        # Initialize telegram notifier for trade reports
        telegram_enabled = bool(runtime_config.get("telegram_enabled", False))
        if telegram_enabled:
            from app.telegram import TelegramNotifier
            telegram_notifier = TelegramNotifier(enabled=True, live=True)
        open_position_symbols = load_open_position_symbols(
            paper_config.state_path
        )

        configured_tracked = scan_config.get("tracked_symbols", [])
        if not isinstance(configured_tracked, list):
            configured_tracked = []
        scan_config = {
            **scan_config,
            "tracked_symbols": list(
                dict.fromkeys(
                    [
                        *[str(value) for value in configured_tracked],
                        *open_position_symbols,
                    ]
                )
            ),
        }

    rankings = scan_symbol_rankings(scan_config, market_data=market_data)

    # Hanya LONG yang dikirim ke paper/live executor.
    results = [item.to_dict() for item in rankings.long]

    # SHORT masih shadow; hanya ditulis ke output.
    short_results = [
        item.to_dict()
        for item in rankings.short
    ]
    tracked_results = [
        item.to_dict()
        for item in rankings.tracked
    ]

    confirmed_short_results = (
        prepare_confirmed_short_signals(
            results,
            short_results,
            scan_config,
        )
    )
    pipeline_signals: list[dict[str, object]] = [
        *results, *confirmed_short_results,
    ]
    for item in [*results, *short_results, *tracked_results]:
        if item.get("data_source") == "sample":
            raise RuntimeError(
                f"Data {item['symbol']} masih sample — koneksi Binance gagal, "
                "bukan data real. Periksa jaringan/rate limit."
            )

    paper: dict[str, object] | None = None
    acr_stats: dict[str, object] | None = None
    acr_config = ACREnrichmentConfig.from_dict(
        runtime_config.get("acr_enrichment") if isinstance(
            runtime_config.get("acr_enrichment"), dict
        ) else None
    )
    if paper_enabled and paper_config is not None:
        paper_signals = prepare_paper_signals(
            [*results, *confirmed_short_results],
            tracked_results,
            open_position_symbols,
        )

        # --- ACR+ Enrichment (Opsi C) ---
        # Fetch HTF candles + inject ltf_candles ke signal dict + apply
        # konfirmasi ACR+ (align / neutral / conflict + optional veto).
        if acr_config.enabled:
            paper_signals, stats_obj = enrich_realtime_signals(
                paper_signals,
                market_data=market_data,
                config=acr_config,
            )
            acr_stats = stats_obj.to_dict()
            # The agent pipeline must consume the exact same ACR-confirmed
            # directional entries as the paper executor, not raw scanner rows.
            pipeline_signals = [
                item for item in paper_signals
                if str(item.get("tracking_reason", "")) != "open_position"
            ]

        paper = RealtimePaperTradingEngine(
            paper_config,
            telegram_notifier
        ).process_signals(paper_signals)

        if acr_stats is not None and isinstance(paper, dict):
            paper["acr_enrichment"] = acr_stats

    elif acr_config.enabled:
        pipeline_signals, stats_obj = enrich_realtime_signals(
            pipeline_signals,
            market_data=market_data,
            config=acr_config,
        )
        acr_stats = stats_obj.to_dict()

    # --- Entry guards (closed candle / regime / liquidity / portfolio heat) ---
    # Applied after ACR so the same vetoed payload flows to paper, agent, and
    # live. Guards are opt-in via configs/realtime.json ``entry_guards`` block.
    guard_config = EntryGuardConfig.from_dict(
        runtime_config.get("entry_guards") if isinstance(
            runtime_config.get("entry_guards"), dict
        ) else None
    )
    if guard_config.enabled:
        paper_state_for_guards = None
        equity_for_guards = 0.0
        if paper_config is not None:
            paper_state_for_guards = read_json_file(
                Path(paper_config.state_path), {}
            )
            if isinstance(paper_state_for_guards, dict):
                equity_for_guards = float(
                    paper_state_for_guards.get("balance", 0.0)
                )
        guard_source = paper_signals if paper_enabled else pipeline_signals
        guard_source = apply_entry_guards(
            guard_source,
            guard_config=guard_config,
            market_data=market_data,
            paper_state=paper_state_for_guards,
            equity=equity_for_guards or 0.0,
        )
        if paper_enabled:
            paper_signals = guard_source
        pipeline_signals = [
            item for item in guard_source
            if str(item.get("tracking_reason", "")) != "open_position"
        ]

    strategy_version = compute_strategy_version().to_dict()
    stamp_strategy_version(pipeline_signals, strategy_version)
    if paper_enabled:
        stamp_strategy_version(paper_signals, strategy_version)

    live_decisions: list[dict[str, object]] = []
    if bool(runtime_config.get("live_execution_enabled", False)):
        live_settings = LiveTradingSettings.from_dict(load_json(live_config_path))
        live_executor = LiveExecutor(live_settings)
        # Live evaluation must use the same ACR-confirmed payload that paper
        # and the agent pipeline consume. Never bypass the shared gate here.
        live_decisions = [
            live_executor.evaluate_signal(signal) for signal in pipeline_signals
        ]

    write_scan_outputs(
        results,
        short_results,
        latest_output,
        history_output,
        paper=paper,
        tracked_results=tracked_results,
    )

    # --- Multi-agent pipeline bridge (advisory, off by default) ---
    # Runs Chart → Learning → Decision on qualified scanner candidates and
    # open positions. Never mutates paper/live state unless
    # ``execute_decisions=true`` is set explicitly.
    agent_pipeline_payload: dict[str, object] | None = None
    agent_pipeline_config = AgentPipelineRuntimeConfig.from_dict(
        runtime_config.get("agent_pipeline") if isinstance(
            runtime_config.get("agent_pipeline"), dict
        ) else None
    )
    if agent_pipeline_config.enabled:
        open_positions_map: dict[str, dict[str, object]] = {}
        if execution_preferences.mode in {"dry_run", "live"} and exchange.lower() == "bitunix":
            try:
                from app.dashboard.routes.multi_portfolio import _load_bitunix_details
                creds = load_exchange_credentials(exchange=exchange.lower())
                if creds is not None and creds.is_configured:
                    details = _load_bitunix_details(creds.api_key, creds.api_secret)
                    for pos in details.get("positions", []) or []:
                        if isinstance(pos, dict) and pos.get("symbol"):
                            symbol = str(pos["symbol"]).upper().replace("-", "/")
                            open_positions_map[symbol] = {
                                **pos,
                                "side": (
                                    "SELL" if str(pos.get("side", "")).upper() == "SHORT"
                                    else "BUY"
                                ),
                                "remaining_size": pos.get("quantity"),
                            }
            except Exception as exc:  # noqa: BLE001
                print(f"bitunix positions fallback to paper: {exc}", flush=True)
        if not open_positions_map and paper is not None:
            for pos in paper.get("open_positions", []) or []:
                if isinstance(pos, dict) and pos.get("symbol"):
                    open_positions_map[str(pos["symbol"])] = pos
        try:
            coordinator = build_runtime_agent_coordinator(
                config=agent_pipeline_config,
                exchange=exchange.lower(),
            )
            agent_pipeline_payload = run_pipeline_bridge(
                config=agent_pipeline_config,
                scanner_results=pipeline_signals,
                open_positions=open_positions_map,
                market_data=market_data,
                coordinator=coordinator,
            )
        except Exception as exc:  # noqa: BLE001
            agent_pipeline_payload = {
                "enabled": True,
                "error": f"pipeline_bridge_failed: {exc}",
            }

    # --- Learning recorder (advisory, off by default) ---
    # Reads new closures from paper_trades.jsonl and records them into the
    # Learning Agent journal. Idempotent via checkpoint file.
    learning_recorder_summary: dict[str, object] | None = None
    learning_recorder_config = LearningRecorderConfig.from_dict(
        runtime_config.get("learning_recorder") if isinstance(
            runtime_config.get("learning_recorder"), dict
        ) else None
    )
    if learning_recorder_config.enabled:
        paper_trades_path: str | None = None
        if paper_config is not None:
            paper_trades_path = paper_config.trades_path
        recorder = build_recorder_if_enabled(
            learning_recorder_config,
            paper_trades_path=paper_trades_path,
        )
        if recorder is not None:
            try:
                new_ids = recorder.process_new_closures()
                learning_recorder_summary = {
                    "enabled": True,
                    "recorded_count": len(new_ids),
                    "recorded_ids": new_ids,
                }
            except Exception as exc:  # noqa: BLE001
                learning_recorder_summary = {
                    "enabled": True,
                    "error": f"recorder_failed: {exc}",
                }
        else:
            learning_recorder_summary = {
                "enabled": True,
                "skipped": "no_trades_path_or_file",
            }

    return {
        "latest_output": latest_output,
        "history_output": history_output,
        "signals": results,
        "short_signals": short_results,
        "tracked_position_signals": tracked_results,
        "confirmed_short_signals": confirmed_short_results,
        "paper": paper,
        "live_decisions": live_decisions,
        "agent_pipeline": agent_pipeline_payload,
        "learning_recorder": learning_recorder_summary,
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
    market_data_cache: dict[tuple[str, bool], MarketDataService] = {}
    stop_requested = False

    def request_stop(signum: int, frame: object) -> None:
        nonlocal stop_requested
        stop_requested = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    while not stop_requested:
        result = run_once(runtime_config, market_data_cache=market_data_cache)
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

        # Jangan pertahankan seluruh payload hasil scan selama interval idle.
        # State penting sudah tersimpan ke file; loop berikutnya akan membuat
        # snapshot baru. Ini hanya melepas referensi, tidak mengubah keputusan.
        del result
        release_unused_memory()

        if args.once:
            break
        for _ in range(interval_seconds):
            if stop_requested:
                break
            time.sleep(1)

    production_shutdown()


if __name__ == "__main__":
    main()
