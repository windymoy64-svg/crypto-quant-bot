from __future__ import annotations

import argparse
import gc
import json
import logging
import signal
import time
_telegram_event_sent_at: dict[str, str] = {}


def notify_live_pipeline_executions(notifier: Any, payload: dict[str, Any]) -> int:
    """Send each newly observed live execution once per pipeline timestamp."""
    delivered = 0
    for collection in (payload.get("entries", []), payload.get("monitor", [])):
        if not isinstance(collection, list):
            continue
        for item in collection:
            if not isinstance(item, dict):
                continue
            result = item.get("result") if isinstance(item.get("result"), dict) else {}
            execution = result.get("execution") if isinstance(result.get("execution"), dict) else {}
            if not execution or not execution.get("results"):
                continue
            key = f"{item.get('symbol', '')}:{payload.get('generated_at', '')}:{execution.get('status', '')}"
            if key in _telegram_event_sent_at:
                continue
            from app.telegram.trade_reporter import TradeReporter
            message = TradeReporter().format_live_execution(result.get("decision", {}), execution)
            if notifier.send(message) is True:
                _telegram_event_sent_at[key] = key
                delivered += 1
    return delivered
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
from app.executor_agent.binance_futures_adapter import BinanceFuturesExecutorAdapter
from app.exchange.binance_futures.client import FuturesEndpoint, FuturesHttpClient
from app.exchange.binance_futures.orders import (
    FuturesLiveSafetyGate,
    FuturesOrderSubmissionEngine,
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
    build_live_recorder_if_enabled,
)


logger = logging.getLogger(__name__)
TELEGRAM_LIVE_CLOSE_CHECKPOINT = Path("logs/telegram_live_close_checkpoint.json")
TELEGRAM_LIVE_PARTIAL_CHECKPOINT = Path("logs/telegram_live_partial_checkpoint.json")


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
    except (AttributeError, OSError, TypeError):
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


def notify_new_bitunix_closes(
    notifier: Any,
    closed_positions: list[dict[str, object]],
    *,
    checkpoint_path: Path = TELEGRAM_LIVE_CLOSE_CHECKPOINT,
) -> int:
    """Deliver each authoritative Bitunix full close exactly once."""

    rows = [row for row in closed_positions if isinstance(row, dict)]
    keys = {
        f"{row.get('position_id') or row.get('symbol')}:{row.get('closed_at') or row.get('update_time')}"
        for row in rows
        if row.get("position_id") or row.get("symbol")
    }
    checkpoint = read_json_file(checkpoint_path, None)
    if not isinstance(checkpoint, dict):
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        checkpoint_path.write_text(
            json.dumps({"seen": sorted(keys)}, indent=2), encoding="utf-8"
        )
        logger.info("Telegram live-close baseline initialized rows=%s", len(keys))
        return 0

    seen = {str(value) for value in checkpoint.get("seen", [])}
    delivered = 0
    from app.telegram.trade_reporter import TradeReporter

    reporter = TradeReporter()
    for row in sorted(rows, key=lambda item: str(item.get("closed_at") or "")):
        key = f"{row.get('position_id') or row.get('symbol')}:{row.get('closed_at') or row.get('update_time')}"
        if key in seen:
            continue
        side = str(row.get("side") or "").upper()
        quantity = abs(float(row.get("quantity") or 0.0))
        position = {
            "symbol": row.get("symbol") or "UNKNOWN",
            "side": "SELL" if side in {"SHORT", "SELL"} else "BUY",
            "entry": float(row.get("entry_price") or row.get("entry") or 0.0),
            "exit": float(row.get("close_price") or row.get("exit") or 0.0),
            "size": quantity,
            "remaining_size": 0.0,
            "realized_pnl": float(row.get("net_pnl", row.get("realized_pnl")) or 0.0),
            "close_reason": row.get("reason") or "exchange_closed",
        }
        if notifier.send(reporter.format_close(position, venue="Bitunix Futures")) is not True:
            logger.warning(
                "Telegram live close delivery failed position_id=%s symbol=%s",
                row.get("position_id"), row.get("symbol"),
            )
            continue
        seen.add(key)
        delivered += 1
        logger.info(
            "Telegram live close delivered position_id=%s symbol=%s",
            row.get("position_id"), row.get("symbol"),
        )

    if delivered:
        temporary = checkpoint_path.with_suffix(checkpoint_path.suffix + ".tmp")
        temporary.write_text(json.dumps({"seen": sorted(seen)}, indent=2), encoding="utf-8")
        temporary.replace(checkpoint_path)
    return delivered


def notify_new_bitunix_partial_closes(
    notifier: Any,
    open_positions: dict[str, dict[str, object]],
    *,
    checkpoint_path: Path = TELEGRAM_LIVE_PARTIAL_CHECKPOINT,
) -> int:
    """Notify when an open Bitunix position quantity decreases between scans."""
    snapshot = {
        str(symbol): {
            "quantity": abs(float(position.get("quantity") or position.get("remaining_size") or 0.0)),
            "position": dict(position),
        }
        for symbol, position in open_positions.items()
        if isinstance(position, dict)
    }
    previous = read_json_file(checkpoint_path, None)
    if not isinstance(previous, dict):
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        checkpoint_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
        logger.info("Telegram live-partial baseline initialized rows=%s", len(snapshot))
        return 0

    from app.telegram.trade_reporter import TradeReporter

    reporter = TradeReporter()
    delivered = 0
    for symbol, current in snapshot.items():
        old = previous.get(symbol)
        if not isinstance(old, dict):
            continue
        old_quantity = abs(float(old.get("quantity") or 0.0))
        current_quantity = abs(float(current.get("quantity") or 0.0))
        closed_quantity = old_quantity - current_quantity
        if closed_quantity <= 1e-12:
            continue

        position = dict(current.get("position") or {})
        side = str(position.get("side") or old.get("position", {}).get("side") or "LONG").upper()
        entry = float(position.get("entry_price") or position.get("entry") or old.get("position", {}).get("entry_price") or 0.0)
        exit_price = float(position.get("last_price") or position.get("mark_price") or position.get("current_price") or entry)
        direction = 1.0 if side in {"LONG", "BUY"} else -1.0
        partial_pnl = (exit_price - entry) * direction * closed_quantity
        reason = "take_profit" if partial_pnl >= 0 else "stop_loss"
        event_position = {
            **position,
            "symbol": position.get("symbol") or symbol,
            "side": "BUY" if side in {"LONG", "BUY"} else "SELL",
            "entry": entry,
            "partial_exit_price": exit_price,
            "partial_size_closed": closed_quantity,
            "remaining_size": current_quantity,
            "partial_realized_pnl": partial_pnl,
            "partial_reason": position.get("partial_reason") or reason,
        }
        if notifier.send(reporter.format_partial_close(event_position, venue="Bitunix Futures")) is True:
            delivered += 1

    temporary = checkpoint_path.with_suffix(checkpoint_path.suffix + ".tmp")
    temporary.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    temporary.replace(checkpoint_path)
    return delivered


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
        raw_symbols = []

    # Pending limit symbols must remain in the tracked scanner universe even
    # after they fall out of top-N. Otherwise no fresh price reaches the paper
    # engine and an order can stay PENDING forever despite touching its zone.
    pending = state.get("pending_orders", {})
    pending_symbols = pending.keys() if isinstance(pending, dict) else (
        (item.get("symbol") for item in pending if isinstance(item, dict))
        if isinstance(pending, list) else []
    )

    seen: set[str] = set()
    symbols: list[str] = []
    for value in [*raw_symbols, *pending_symbols]:
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
    pending_entry_symbols: set[str] | None = None,
    exchange_positions: list[dict[str, Any]] | None = None,
) -> AgentPipelineCoordinator:
    """Build coordinator with optional per-agent LLM + exchange executor.

    LLM clients are loaded from operator settings (dashboard). Missing model /
    key means that agent stays deterministic. Chart/Learning/Decision can be
    active LLM agents; Executor LLM remains explain-only when configured.
    """

    from app.learning_agent.agent import LearningAgent
    from app.llm.factory import build_agent_llm

    execution = load_execution_preferences()
    coordinator_config = AgentPipelineConfig(
        min_scanner_confidence=config.min_scanner_confidence,
        execute_decisions=config.execute_decisions,
        allow_watch_soft_entry=bool(getattr(config, "allow_watch_soft_entry", False)),
        min_watch_confidence=float(getattr(config, "min_watch_confidence", 75.0)),
        chart_llm_propose=bool(getattr(config, "chart_llm_propose", True)),
        adopt_chart_proposal_levels=bool(getattr(config, "adopt_chart_proposal_levels", False)),
        decision_llm_can_veto=bool(getattr(config, "decision_llm_can_veto", True)),
        decision_llm_veto_min_confidence=float(
            getattr(config, "decision_llm_veto_min_confidence", 0.75)
        ),
        apply_llm_policy=bool(getattr(config, "apply_llm_policy", False)),
        policy_min_confidence=float(getattr(config, "policy_min_confidence", 0.6)),
        scanner_chart_conflict_policy=str(
            getattr(config, "scanner_chart_conflict_policy", "REJECT")
        ).upper(),
    )

    chart_llm_client, chart_llm_model, chart_llm_base_url = build_agent_llm("chart")
    learning_llm_client, learning_llm_model, learning_llm_base_url = build_agent_llm("learning")
    decision_llm_client, decision_llm_model, decision_llm_base_url = build_agent_llm("decision")
    executor_llm_client, executor_llm_model, executor_llm_base_url = build_agent_llm("executor")

    learning_agent = LearningAgent(
        llm_client=learning_llm_client,
        llm_model=learning_llm_model,
        llm_base_url=learning_llm_base_url or "",
    )
    llm_kwargs = {
        "learning_agent": learning_agent,
        "chart_llm_client": chart_llm_client,
        "chart_llm_model": chart_llm_model,
        "chart_llm_base_url": chart_llm_base_url or "",
        "decision_llm_client": decision_llm_client,
        "decision_llm_model": decision_llm_model,
        "decision_llm_base_url": decision_llm_base_url or "",
        "executor_llm_client": executor_llm_client,
        "executor_llm_model": executor_llm_model,
        "executor_llm_base_url": executor_llm_base_url or "",
        "config": coordinator_config,
    }

    if execution.mode == "paper":
        return AgentPipelineCoordinator(
            executor_agent=ExecutorAgent(), **llm_kwargs,
        )

    credentials = load_exchange_credentials(exchange=exchange)
    if credentials is None or not credentials.is_configured:
        if execution.mode == "dry_run":
            return AgentPipelineCoordinator(
                executor_agent=ExecutorAgent(), **llm_kwargs,
            )
        return AgentPipelineCoordinator(
            executor_agent=ExecutorAgent(live=True), **llm_kwargs,
        )

    network_enabled = execution.network_enabled
    try:
        trading = load_trading_preferences(exchange=exchange)
        leverage = trading.leverage or 1
        target_margin_percent = trading.target_margin_percent
        target_risk_reward = trading.target_risk_reward
        take_profit_percent = trading.take_profit_percent
        stop_loss_percent = trading.stop_loss_percent
        trailing_stop_percent = trading.trailing_stop_percent
    except Exception:
        leverage = 1
        target_margin_percent = None
        target_risk_reward = None
        take_profit_percent = None
        stop_loss_percent = None
        trailing_stop_percent = None
    if exchange == "bitunix":
        adapter = BitunixFuturesExecutorAdapter(
            BitunixCredentials(credentials.api_key, credentials.api_secret),
            safety_gate=BitunixLiveSafetyGate(
                enabled=True,
                dry_run=not network_enabled,
                confirm_live=execution.live_confirmed,
            ),
            leverage=leverage,
            blocked_entry_symbols=pending_entry_symbols,
        )
    elif exchange == "binance":
        endpoint = FuturesEndpoint.TESTNET if credentials.testnet else FuturesEndpoint.MAINNET
        client = FuturesHttpClient(
            credentials.api_key,
            credentials.api_secret,
            endpoint=endpoint,
        )
        gate = FuturesLiveSafetyGate(
            enabled=True,
            dry_run=not network_enabled,
            confirm_live=execution.live_confirmed,
        )
        adapter = BinanceFuturesExecutorAdapter(
            FuturesOrderSubmissionEngine(client, gate),
        )
    else:
        return AgentPipelineCoordinator(
            executor_agent=ExecutorAgent(live=True), **llm_kwargs,
        )
    if network_enabled and config.allow_live_orders and exchange_positions:
        reconciliation = adapter.reconcile_take_profits(
            exchange_positions, timestamp=datetime.now(tz=UTC).isoformat(),
        )
        for result in reconciliation:
            log = logger.info if result.status != "REJECTED" else logger.error
            log(
                "Bitunix TP reconciliation symbol=%s role=%s status=%s "
                "quantity=%s order_id=%s reason=%s",
                result.symbol,
                result.meta.get("role", "take_profit"),
                result.status,
                result.requested_quantity,
                result.order_id,
                result.reason,
            )
        repairs = adapter.repair_unprotected_positions(
            exchange_positions, timestamp=datetime.now(tz=UTC).isoformat(),
        )
        for result in repairs:
            log = logger.info if result.status != "REJECTED" else logger.error
            log(
                "Bitunix TP repair symbol=%s role=%s status=%s quantity=%s "
                "order_id=%s reason=%s",
                result.symbol,
                result.meta.get("role", "take_profit"),
                result.status,
                result.requested_quantity,
                result.order_id,
                result.reason,
            )
    balance = 10_000.0
    if network_enabled:
        balance = adapter.available_balance("USDT")
        if balance <= 0:
            logger.error(
                "Live preflight failed: exchange returned no available USDT balance"
            )
    return AgentPipelineCoordinator(
        executor_agent=ExecutorAgent(
            balance=balance,
            leverage=leverage,
            target_margin_percent=target_margin_percent,
            target_risk_reward=target_risk_reward,
            take_profit_percent=take_profit_percent,
            stop_loss_percent=stop_loss_percent,
            trailing_stop_percent=trailing_stop_percent,
            live=True,
            exchange_adapter=adapter,
            # Full paper parity achieved: three-stage TP, BE/trailing via HOLD state machine,
            # shared ACR swing trailing, and unified EXIT gate with PnL-R filtering.
            paper_parity_verified=True,
        ),
        **llm_kwargs,
    )


def reconcile_live_take_profits_at_startup(runtime_config: dict[str, object]) -> None:
    """Protect existing Bitunix positions before the first market scan.

    The normal agent bridge also reconciles queued TP1 plans, but it runs only
    after market scanning. Startup protection must not wait for a slow scan.
    """

    execution = load_execution_preferences()
    portfolio = load_portfolio_preferences()
    agent_config = AgentPipelineRuntimeConfig.from_dict(
        runtime_config.get("agent_pipeline")
        if isinstance(runtime_config.get("agent_pipeline"), dict)
        else None
    )
    exchange = str(portfolio.active_execution_exchange or "").lower()
    if (
        execution.mode != "live"
        or not execution.network_enabled
        or not execution.live_confirmed
        or exchange != "bitunix"
        or not agent_config.enabled
        or not agent_config.allow_live_orders
    ):
        return

    credentials = load_exchange_credentials(exchange="bitunix")
    if credentials is None or not credentials.is_configured:
        return
    from app.dashboard.routes.multi_portfolio import _load_bitunix_details

    details = _load_bitunix_details(credentials.api_key, credentials.api_secret)
    # Include protected positions too so the adapter can prune stale local TP
    # queues without submitting duplicate exchange orders.
    positions = [
        position for position in details.get("positions", []) or []
        if isinstance(position, dict)
    ]
    if not positions:
        return
    adapter = BitunixFuturesExecutorAdapter(
        BitunixCredentials(credentials.api_key, credentials.api_secret),
        safety_gate=BitunixLiveSafetyGate(
            enabled=True, dry_run=False, confirm_live=True,
        ),
    )
    repair = getattr(adapter, "repair_unprotected_positions", None)
    repairs = (
        repair(positions, timestamp=datetime.now(tz=UTC).isoformat())
        if callable(repair) else []
    )
    results = adapter.reconcile_take_profits(
        positions, timestamp=datetime.now(tz=UTC).isoformat(),
    )
    results = [*repairs, *results]
    for result in results:
        log = logger.info if result.status != "REJECTED" else logger.error
        log(
            "Bitunix startup TP reconciliation symbol=%s status=%s quantity=%s "
            "order_id=%s reason=%s",
            result.symbol, result.status, result.requested_quantity,
            result.order_id, result.reason,
        )


def register_existing_live_lifecycle_positions(
    positions: list[dict[str, object]],
    *,
    adapter: BitunixFuturesExecutorAdapter,
) -> None:
    """Load persisted lifecycle states for already-open live positions.

    Existing positions are not adopted here. Registration is created only by
    the lifecycle plan reconciliation; this function makes those persisted
    states available to the monitor immediately after a restart.
    """
    from app.execution.live_lifecycle import LiveLifecycleStore

    store = LiveLifecycleStore(getattr(adapter, "_lifecycle_store_path", "logs/bitunix_live_lifecycle.json"))
    states = store.load()
    open_ids = {
        str(position.get("position_id") or "")
        for position in positions
        if isinstance(position, dict)
    }
    stale_ids = [key for key in states if key not in open_ids]
    if stale_ids:
        for key in stale_ids:
            states.pop(key, None)
        store.save(states)
    from app.execution.live_lifecycle import LiveLifecycleController

    controller = LiveLifecycleController(adapter, store)
    for position in positions:
        if isinstance(position, dict) and str(position.get("position_id") or "") not in states:
            controller.register_existing_position(position)


def build_standalone_bitunix_adapter() -> BitunixFuturesExecutorAdapter | None:
    """Build a Bitunix adapter without depending on the agent coordinator.

    Trailing protection must keep working even when the pipeline coordinator
    fails to build (e.g. balance preflight error) or is not yet available.
    """
    try:
        credentials = load_exchange_credentials(exchange="bitunix")
        if credentials is None or not credentials.is_configured:
            return None
        execution = load_execution_preferences()
        return BitunixFuturesExecutorAdapter(
            BitunixCredentials(credentials.api_key, credentials.api_secret),
            safety_gate=BitunixLiveSafetyGate(
                enabled=True,
                dry_run=not execution.network_enabled,
                confirm_live=execution.live_confirmed,
            ),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("standalone bitunix adapter unavailable: %s", exc)
        return None


def resolve_live_bitunix_lifecycle_adapter(
    coordinator: AgentPipelineCoordinator | None,
) -> BitunixFuturesExecutorAdapter | None:
    """Resolve the Bitunix adapter used by live lifecycle protection.

    Prefer the coordinator's own exchange adapter (single instance), then fall
    back to a standalone adapter so trailing never depends on pipeline health.
    """
    adapter = (
        getattr(coordinator.executor_agent, "_exchange", None)
        if coordinator is not None
        else None
    )
    if isinstance(adapter, BitunixFuturesExecutorAdapter):
        return adapter
    return build_standalone_bitunix_adapter()


def apply_live_trailing_protection(
    *,
    coordinator: AgentPipelineCoordinator | None,
    trailing_stop_percent: float | None,
    open_positions_map: dict[str, dict[str, object]],
    market_data: MarketDataService,
    timeframe: str,
    limit: int,
) -> list[dict[str, object]]:
    """Run live trailing protection for every open Bitunix position.

    Independent of agent decisions and monitor output; the percent travels as an
    explicit parameter (no hidden scope). Falls back to a standalone adapter when
    the coordinator is unavailable. Returns per-position lifecycle updates.
    """
    updates: list[dict[str, object]] = []
    logger.info(
        "trailing_dispatch percent=%s position_count=%d symbols=%s",
        trailing_stop_percent,
        len(open_positions_map),
        sorted(str(symbol) for symbol in open_positions_map),
    )
    try:
        adapter = resolve_live_bitunix_lifecycle_adapter(coordinator)
        if not isinstance(adapter, BitunixFuturesExecutorAdapter):
            return [{
                "managed": False,
                "error": "live_trailing_unavailable:no_bitunix_adapter",
            }]
        from app.execution.live_lifecycle import (
            LiveLifecycleController,
            LiveLifecycleStore,
            apply_live_lifecycle_monitor,
        )

        try:
            # Registration is idempotent per position. This keeps the trailing
            # loop effective even when the coordinator path never registered.
            register_existing_live_lifecycle_positions(
                list(open_positions_map.values()), adapter=adapter,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("live lifecycle registration failed: %s", exc)
        controller = LiveLifecycleController(
            adapter,
            store=LiveLifecycleStore(
                getattr(adapter, "_lifecycle_store_path", "logs/bitunix_live_lifecycle.json")
            ),
            trailing_stop_percent=trailing_stop_percent,
        )
        for symbol, position in open_positions_map.items():
            if not isinstance(position, dict):
                continue
            try:
                logger.info(
                    "trailing_fetch symbol=%s position_id=%s",
                    symbol, position.get("position_id"),
                )
                fetched = market_data.fetch_ohlcv(
                    symbol, timeframe=timeframe, limit=limit,
                )
                candles = list(getattr(fetched, "candles", []) or [])
                result = apply_live_lifecycle_monitor(
                    controller, position=position, decision={},
                    ltf_candles=candles,
                )
                updates.append(result)
                logger.info(
                    "trailing_result symbol=%s position_id=%s managed=%s new_stop=%s error=%s",
                    symbol, position.get("position_id"), result.get("managed"),
                    result.get("new_stop"), result.get("error", ""),
                )
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "trailing_fetch_failed symbol=%s position_id=%s error=%s",
                    symbol, position.get("position_id"), exc,
                )
                updates.append({
                    "managed": False, "position_id": position.get("position_id"),
                    "error": f"live_trailing_failed:{exc}",
                })
    except Exception as exc:  # noqa: BLE001
        # Fail closed: lifecycle mutation failure is exposed in the artifact.
        updates.append({
            "managed": False, "error": f"live_lifecycle_failed:{exc}",
        })
    return updates


def write_live_trailing_artifact(
    path: str,
    *,
    trailing_stop_percent: float | None,
    updates: list[dict[str, object]],
) -> None:
    """Persist the latest trailing result independently from scan output."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "exchange": "bitunix",
        "trailing_stop_percent": trailing_stop_percent,
        "updates": updates,
    }
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(target)


def write_scan_outputs(
    results: list[dict[str, object]],
    short_results: list[dict[str, object]],
    latest_output: str,
    history_output: str,
    paper: dict[str, object] | None = None,
    tracked_results: list[dict[str, object]] | None = None,
    market_breadth: dict[str, object] | None = None,
    move_alerts: list[dict[str, object]] | None = None,
    scan_stats: dict[str, object] | None = None,
) -> None:
    now = datetime.now(tz=UTC).isoformat()
    payload = {
        "timestamp": now,
        "signals": results,
        "short_signals": short_results,
        # Simbol posisi terbuka yang keluar dari top N tetap dikirim ke
        # dashboard agar harganya ikut realtime setiap siklus scan.
        "tracked_signals": tracked_results or [],
        "market_breadth": market_breadth or {},
        "move_alerts": move_alerts or [],
        "scan_stats": scan_stats or {},
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
    trailing_output = str(
        runtime_config.get("trailing_output", "logs/live_trailing_status.json")
    )

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
    # Trailing protection reads the operator setting directly in this scope.
    # The coordinator's builder keeps its own copy for entry geometry, but the
    # live lifecycle wiring must never depend on that local variable.
    trailing_stop_percent: float | None = None
    if execution_preferences.mode == "live" and exchange.lower() == "bitunix":
        try:
            trailing_stop_percent = load_trading_preferences(
                exchange=exchange.lower()
            ).trailing_stop_percent
        except Exception as exc:  # noqa: BLE001
            logger.warning("live trailing percent unavailable: %s", exc)
    logger.info(
        "trailing_config exchange=%s mode=%s network_enabled=%s percent=%s",
        exchange.lower(), execution_preferences.mode,
        execution_preferences.network_enabled, trailing_stop_percent,
    )
    paper_enabled = bool(runtime_config.get("paper_trading_enabled", True)) and (
        execution_preferences.mode == "paper"
    )
    paper_config: PaperTradingConfig | None = None
    paper_engine: RealtimePaperTradingEngine | None = None
    open_position_symbols: list[str] = []

    # Initialize telegram notifier for trade reports (works for BOTH paper & live modes)
    telegram_notifier = None
    from app.settings.telegram_preferences import load_telegram_credentials
    bot_token, chat_id, telegram_enabled = load_telegram_credentials()
    if telegram_enabled:
        from app.telegram import TelegramNotifier
        logger.info(f"Telegram notifications enabled in config")

        # Get credentials - try environment first, then fallback to .env file
        if bot_token and chat_id:
            telegram_notifier = TelegramNotifier(
                enabled=True,
                # ``live`` controls real Telegram API delivery, not whether
                # order execution is paper or live. Notifications must be
                # delivered in both trading modes when explicitly enabled.
                live=True,
                token=bot_token,
                chat_id=chat_id
            )
            logger.info(f"✅ Telegram notifier initialized successfully (mode={execution_preferences.mode})")
        else:
            logger.warning(
                "❌ Telegram notifications enabled but credentials missing. "
                f"Token present: {bool(bot_token)}, Chat ID present: {bool(chat_id)}. "
                "Check /opt/crypto-quant-bot/.env file."
            )

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
                "target_margin_percent": preferences.target_margin_percent,
                "target_risk_reward": preferences.target_risk_reward,
            }
        paper_config = PaperTradingConfig.from_dict(
            paper_data
        )
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

        paper_engine = RealtimePaperTradingEngine(
            paper_config,
            telegram_notifier
        )
        # When agent execution is active, scanner remains the candidate source
        # and price feed, but must not open a position directly. New entries
        # are routed below from Chart Agent -> Decision Agent so market/limit
        # zone semantics cannot be bypassed by the scanner's last close.
        agent_cfg_raw = runtime_config.get("agent_pipeline")
        agent_controls_entries = bool(
            isinstance(agent_cfg_raw, dict)
            and agent_cfg_raw.get("enabled")
            and agent_cfg_raw.get("execute_decisions")
        )
        paper_execution_signals = paper_signals
        if agent_controls_entries:
            paper_execution_signals = []
            open_symbols = set(open_position_symbols)
            for item in paper_signals:
                copied = dict(item)
                if (
                    str(copied.get("symbol", "")) not in open_symbols
                    and str(copied.get("action", "")).upper() in {"BUY", "SELL"}
                ):
                    copied["action"] = "SKIP"
                    copied["tracking_reason"] = "awaiting_chart_agent_zone"
                paper_execution_signals.append(copied)
        paper = paper_engine.process_signals(paper_execution_signals)

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
        if live_settings.exchange.lower() != exchange.lower():
            # Never let the legacy CCXT route submit to a different venue than
            # the scanner/active execution exchange. The agent adapter path is
            # the canonical futures execution route.
            live_decisions = [
                {
                    "status": "blocked",
                    "symbol": str(signal.get("symbol", "")),
                    "reason": "live_exchange_mismatch",
                    "scanner_exchange": exchange.lower(),
                    "live_exchange": live_settings.exchange.lower(),
                }
                for signal in pipeline_signals
            ]
        else:
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
        market_breadth=(
            rankings.market_breadth
            if isinstance(getattr(rankings, "market_breadth", None), dict)
            else {}
        ),
        move_alerts=(
            rankings.move_alerts
            if isinstance(getattr(rankings, "move_alerts", None), list)
            else []
        ),
        scan_stats=(
            rankings.scan_stats
            if isinstance(getattr(rankings, "scan_stats", None), dict)
            else {}
        ),
    )

    # --- Multi-agent pipeline bridge (advisory, off by default) ---
    # Runs Chart → Learning → Decision on qualified scanner candidates and
    # open positions. Never mutates paper/live state unless
    # ``execute_decisions=true`` is set explicitly.
    agent_pipeline_payload: dict[str, object] | None = None
    live_lifecycle_updates: list[dict[str, object]] = []
    live_closed_positions: list[dict[str, object]] = []
    agent_pipeline_config = AgentPipelineRuntimeConfig.from_dict(
        runtime_config.get("agent_pipeline") if isinstance(
            runtime_config.get("agent_pipeline"), dict
        ) else None
    )
    if agent_pipeline_config.enabled or (
        execution_preferences.mode == "live"
        and exchange.lower() == "bitunix"
    ):
        coordinator: AgentPipelineCoordinator | None = None
        open_positions_map: dict[str, dict[str, object]] = {}
        live_partial_close_symbols: set[str] = set()
        pending_entry_symbols: set[str] = set()
        pending_orders_read_ok = execution_preferences.mode not in {"dry_run", "live"}
        if execution_preferences.mode in {"dry_run", "live"} and exchange.lower() == "bitunix":
            try:
                from app.dashboard.routes.multi_portfolio import _load_bitunix_details
                creds = load_exchange_credentials(exchange=exchange.lower())
                if creds is not None and creds.is_configured:
                    details = _load_bitunix_details(creds.api_key, creds.api_secret)
                    live_closed_positions = [
                        row for row in details.get("closed_positions", [])
                        if isinstance(row, dict)
                    ]
                    if telegram_notifier is not None:
                        notify_new_bitunix_closes(
                            telegram_notifier,
                            live_closed_positions,
                        )
                    warnings = [str(value) for value in details.get("warnings", [])]
                    pending_orders_read_ok = not any(
                        value.startswith("pending_orders:") for value in warnings
                    )
                    for pos in details.get("positions", []) or []:
                        if isinstance(pos, dict) and pos.get("symbol"):
                            compact = str(pos["symbol"]).upper().replace("-", "/")
                            symbol = (
                                f"{compact[:-4]}/USDT"
                                if "/" not in compact and compact.endswith("USDT")
                                else compact
                            )
                            open_positions_map[symbol] = {
                                **pos,
                                "side": (
                                    "SELL" if str(pos.get("side", "")).upper() in {"SHORT", "SELL"}
                                    else "BUY"
                                ),
                                "remaining_size": pos.get("quantity"),
                            }
                            pending_entry_symbols.add(symbol)
                    previous_partial_snapshot = read_json_file(
                        TELEGRAM_LIVE_PARTIAL_CHECKPOINT, None,
                    )
                    if isinstance(previous_partial_snapshot, dict):
                        for symbol, position in open_positions_map.items():
                            previous = previous_partial_snapshot.get(symbol)
                            if not isinstance(previous, dict):
                                continue
                            old_quantity = abs(float(previous.get("quantity") or 0.0))
                            current_quantity = abs(float(position.get("quantity") or 0.0))
                            if old_quantity - current_quantity > 1e-12:
                                live_partial_close_symbols.add(symbol)
                    for order in details.get("open_orders", []) or []:
                        if not isinstance(order, dict):
                            continue
                        # A pending entry already reserves this symbol. Do not
                        # submit another LIMIT while the exchange order remains
                        # NEW/PART_FILLED. Protective reduce-only orders do not
                        # block a new entry, but get_pending_orders only returns
                        # the entry orders for this path in normal operation.
                        if bool(order.get("reduce_only")):
                            continue
                        status = str(order.get("status") or "").upper().rstrip("_")
                        if status in {"NEW", "PART_FILLED", "INIT"} and order.get("symbol"):
                            compact = str(order["symbol"]).upper().replace("-", "/")
                            pending_entry_symbols.add(
                                f"{compact[:-4]}/USDT"
                                if "/" not in compact and compact.endswith("USDT")
                                else compact
                            )
                    if telegram_notifier is not None:
                        notify_new_bitunix_partial_closes(
                            telegram_notifier,
                            open_positions_map,
                        )
            except Exception as exc:  # noqa: BLE001
                pending_orders_read_ok = False
                print(f"bitunix positions fallback to paper: {exc}", flush=True)
        if not open_positions_map and paper is not None:
            for pos in paper.get("open_positions", []) or []:
                if isinstance(pos, dict) and pos.get("symbol"):
                    open_positions_map[str(pos["symbol"])] = pos
        if execution_preferences.mode == "live" and exchange.lower() == "bitunix":
            # A live position without exchange-confirmed TP must reserve its
            # symbol. Never open another position while protection is missing.
            for live_position in open_positions_map.values():
                if not isinstance(live_position, dict):
                    continue
                has_tp = bool(
                    live_position.get("take_profit")
                    or live_position.get("take_profits")
                    or live_position.get("take_profit_order_count")
                )
                if not has_tp and live_position.get("symbol"):
                    pending_entry_symbols.add(str(live_position["symbol"]))

        # Trailing protection runs immediately after positions are fetched.
        # It must not wait for TP repair, coordinator construction, or agent
        # decisions; a TP failure must never suppress stop protection.
        if (
            execution_preferences.mode == "live"
            and execution_preferences.network_enabled
            and exchange.lower() == "bitunix"
            and open_positions_map
        ):
            live_lifecycle_updates = apply_live_trailing_protection(
                coordinator=None,
                trailing_stop_percent=trailing_stop_percent,
                open_positions_map=open_positions_map,
                market_data=market_data,
                timeframe=agent_pipeline_config.ltf_timeframe,
                limit=agent_pipeline_config.ltf_limit,
            )
            write_live_trailing_artifact(
                trailing_output,
                trailing_stop_percent=trailing_stop_percent,
                updates=live_lifecycle_updates,
            )
            if live_lifecycle_updates and isinstance(agent_pipeline_payload, dict):
                agent_pipeline_payload["live_lifecycle_updates"] = live_lifecycle_updates

        try:
            coordinator = build_runtime_agent_coordinator(
                config=agent_pipeline_config,
                exchange=exchange.lower(),
                pending_entry_symbols=pending_entry_symbols,
                exchange_positions=list(open_positions_map.values()),
            )
            # Private pending-order state is a mandatory live idempotency input.
            # If Bitunix cannot be read, fail closed instead of assuming no
            # pending entries and risking duplicate exposure.
            if (
                execution_preferences.mode == "live"
                and exchange.lower() == "bitunix"
                and not pending_orders_read_ok
            ):
                coordinator.executor_agent.live = False
            lifecycle_adapter = getattr(coordinator.executor_agent, "_exchange", None)
            if isinstance(lifecycle_adapter, BitunixFuturesExecutorAdapter):
                register_existing_live_lifecycle_positions(
                    list(open_positions_map.values()), adapter=lifecycle_adapter,
                )
            # Soft-entry needs raw scanner WATCH rows. ACR enrichment often
            # rewrites non-confirmed directional rows to SKIP, which would hide
            # WATCH candidates from the agent entirely.
            agent_scanner_results = list(pipeline_signals)
            if agent_pipeline_config.allow_watch_soft_entry:
                seen = {
                    str(item.get("symbol"))
                    for item in agent_scanner_results
                    if isinstance(item, dict)
                }
                for item in [*results, *short_results]:
                    if not isinstance(item, dict):
                        continue
                    symbol = str(item.get("symbol") or "")
                    if not symbol or symbol in seen:
                        continue
                    long_action = str(item.get("action") or "").upper()
                    short_action = str(item.get("short_action") or "").upper()
                    if long_action == "WATCH" or short_action == "WATCH":
                        agent_scanner_results.append(item)
                        seen.add(symbol)
            agent_pipeline_payload = run_pipeline_bridge(
                config=agent_pipeline_config,
                scanner_results=agent_scanner_results,
                open_positions=open_positions_map,
                pending_entry_symbols=pending_entry_symbols,
                market_data=market_data,
                coordinator=coordinator,
            )
            if live_lifecycle_updates:
                agent_pipeline_payload["live_lifecycle_updates"] = live_lifecycle_updates
            if telegram_notifier is not None:
                notify_live_pipeline_executions(telegram_notifier, agent_pipeline_payload)
        except Exception as exc:  # noqa: BLE001
            agent_pipeline_payload = {
                "enabled": True,
                "error": f"pipeline_bridge_failed: {exc}",
            }

        # Bitunix may consume or detach the remaining TPSL ladder after a
        # partial close. Restore missing levels from the registered lifecycle.
        if (
            live_partial_close_symbols
            and execution_preferences.mode == "live"
            and execution_preferences.network_enabled
            and exchange.lower() == "bitunix"
            and coordinator is not None
        ):
            try:
                from app.execution.live_lifecycle import LiveLifecycleController

                adapter = getattr(coordinator.executor_agent, "_exchange", None)
                if isinstance(adapter, BitunixFuturesExecutorAdapter):
                    controller = LiveLifecycleController(adapter)
                    for symbol in live_partial_close_symbols:
                        position = open_positions_map.get(symbol)
                        if not isinstance(position, dict):
                            continue
                        roles = controller.rearm_remaining_take_profits(position)
                        if roles:
                            logger.info(
                                "Bitunix TP re-arm symbol=%s roles=%s",
                                symbol, roles,
                            )
            except Exception as exc:  # noqa: BLE001
                logger.error("Bitunix TP re-arm failed: %s", exc)

        # --- Decision → Paper execution bridge ---
        # When the Decision Agent returns EXIT for an open position, route it to
        # the paper engine so the advisory decision actually closes the trade.
        # Priority gate (close_from_decision) decides whether to act based on
        # urgency (CHoCH = always; bias flip / confluence low = only losers or
        # big winners >1R). Only runs in paper mode where ``paper_engine`` lives.
        agent_exit_executions: list[dict[str, object]] = []
        if (
            isinstance(agent_pipeline_payload, dict)
            and agent_pipeline_config.enabled
            and agent_pipeline_config.execute_decisions
            and paper_enabled
            and paper_engine is not None
        ):
            # Route approved Chart/Decision Agent entries to paper. LIMIT plans
            # wait for the zone instead of buying the current momentum peak.
            agent_entry_signals: list[dict[str, object]] = []
            current_by_symbol = {
                str(item.get("symbol")): float(item.get("entry", 0.0))
                for item in pipeline_signals if isinstance(item, dict)
            }
            for entry in agent_pipeline_payload.get("entries") or []:
                if not isinstance(entry, dict) or entry.get("skipped"):
                    continue
                result = entry.get("result") or {}
                decision = result.get("decision") or {}
                action = str(decision.get("action", "")).upper()
                plan = decision.get("entry_plan") or {}
                symbol = str(entry.get("symbol") or decision.get("symbol") or "")
                if action not in {"ENTRY_BUY", "ENTRY_SELL"} or not symbol or not plan:
                    continue
                zone = plan.get("entry_zone") or [plan.get("entry_price"), plan.get("entry_price")]
                current = current_by_symbol.get(symbol, float(plan.get("entry_price", 0.0)))
                low, high = sorted((float(zone[0]), float(zone[1])))
                mode = str(plan.get("order_type", "MARKET")).upper()
                if mode not in {"MARKET", "LIMIT"}:
                    mode = "MARKET"
                dmeta = decision.get("meta") or {}
                agent_entry_signals.append({
                    "symbol": symbol,
                    "action": "BUY" if action == "ENTRY_BUY" else "SELL",
                    "entry": current if mode == "MARKET" else float(plan.get("entry_price")),
                    "current_price": current,
                    "entry_zone": [low, high],
                    "entry_mode": mode,
                    "zone_limit": mode == "LIMIT",
                    "stop_loss": float(plan.get("stop_loss")),
                    "take_profit": [
                        value for value in [plan.get("take_profit_1"), plan.get("take_profit_2"), plan.get("take_profit_3")]
                        if value is not None
                    ],
                    "confidence": float(decision.get("confidence_score", 0.0)),
                    "score": float(decision.get("confluence_score", 0.0)),
                    "entry_reason": "chart_agent_zone",
                    "expires_in_seconds": float(plan.get("expires_in_seconds", 900.0)),
                    # Trend-hold at open: skip fixed TP ladder until HTF flips.
                    "tp1_enabled": bool(dmeta.get("tp1_enabled", True)),
                    "hold_mode": bool(dmeta.get("hold_mode", False)),
                    "skip_fixed_tp": bool(dmeta.get("skip_fixed_tp", False)),
                })
            if agent_entry_signals:
                paper = paper_engine.process_signals(agent_entry_signals)

            monitor_results = agent_pipeline_payload.get("monitor") or []
            paper_state_path = (
                paper_config.state_path if paper_config is not None else ""
            )
            paper_state_for_exits = read_json_file(Path(paper_state_path), {}) if paper_state_path else {}
            open_positions_snapshot = (
                paper_state_for_exits.get("open_positions") if isinstance(paper_state_for_exits, dict) else None
            ) or {}
            for entry in monitor_results:
                if not isinstance(entry, dict) or entry.get("skipped"):
                    continue
                result = entry.get("result") or {}
                decision = result.get("decision") or {}
                action = str(decision.get("action", "")).upper()
                symbol = str(entry.get("symbol") or decision.get("symbol") or "")
                if not symbol:
                    continue

                # HOLD → sync dynamic TP1 flag onto the open position. Strong
                # structure disables TP1 (let runner reach TP2/TP3); weak
                # structure keeps TP1 to lock partial profit.
                if action == "HOLD":
                    meta = decision.get("meta") or {}
                    if "tp1_enabled" in meta:
                        paper_engine.update_tp1_flag(
                            symbol=symbol, enabled=bool(meta["tp1_enabled"]),
                        )
                    continue

                if action != "EXIT":
                    continue
                position = open_positions_snapshot.get(symbol)
                if not isinstance(position, dict):
                    continue
                exit_plan = decision.get("exit_plan") or {}
                urgency = str(exit_plan.get("urgency", "NEXT_CANDLE")).upper()
                last_price = float(position.get("last_price", position.get("entry", 0.0)))
                # PnL ratio = unrealized PnL / risk_amount (1R).
                risk_amount = abs(
                    float(position.get("entry", 0.0))
                    - float(position.get("static_stop_loss") or position.get("stop_loss") or 0.0)
                ) * float(position.get("remaining_size") or position.get("size") or 0.0)
                unrealized = float(position.get("unrealized_pnl", 0.0))
                pnl_ratio = (unrealized / risk_amount) if risk_amount > 0 else 0.0
                reason = str(exit_plan.get("reason") or "agent_decision_exit")
                min_hold = float(
                    getattr(agent_pipeline_config, "min_hold_seconds", 300.0)
                    or 300.0
                )
                closed = paper_engine.close_from_decision(
                    symbol=symbol,
                    exit_price=last_price,
                    reason=reason,
                    urgency=urgency,
                    pnl_ratio=pnl_ratio,
                    min_hold_seconds=min_hold,
                )
                agent_exit_executions.append({
                    "symbol": symbol,
                    "urgency": urgency,
                    "pnl_ratio": round(pnl_ratio, 3),
                    "reason": reason,
                    "closed": closed is not None,
                })
            if agent_exit_executions:
                agent_pipeline_payload["exit_executions"] = agent_exit_executions

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
        if execution_preferences.mode == "live" and live_closed_positions:
            live_recorder = build_live_recorder_if_enabled(learning_recorder_config)
            if live_recorder is not None:
                try:
                    live_ids = live_recorder.process_bitunix_closed_positions(
                        live_closed_positions
                    )
                    learning_recorder_summary = {
                        "enabled": True,
                        "recorded_count": len(live_ids),
                        "recorded_ids": live_ids,
                        "source": "bitunix_closed_positions",
                    }
                except Exception as exc:  # noqa: BLE001
                    learning_recorder_summary = {
                        "enabled": True,
                        "error": f"live_recorder_failed: {exc}",
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
        "scan_stats": (
            rankings.scan_stats
            if isinstance(getattr(rankings, "scan_stats", None), dict)
            else {}
        ),
    }


def main() -> None:
    setup_production_logging()
    production_startup()
    parser = argparse.ArgumentParser(description="Run realtime crypto market scanner")
    parser.add_argument("--config", default="configs/realtime.json")
    parser.add_argument("--once", action="store_true", help="Run one scan and exit")
    args = parser.parse_args()

    runtime_config = load_json(args.config)
    try:
        reconcile_live_take_profits_at_startup(runtime_config)
    except Exception:
        # Keep the scanner alive, but emit a loud error: existing SL remains
        # exchange-side while TP reconciliation retries in the agent bridge.
        logger.exception("Bitunix startup TP reconciliation failed")
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
        scan_stats = result.get("scan_stats") if isinstance(result.get("scan_stats"), dict) else {}
        scan_summary = ""
        if scan_stats:
            scan_summary = (
                f" | scan prefilter={scan_stats.get('prefilter_count', 0)}"
                f" scanned={scan_stats.get('scanned_count', 0)}"
                f" skipped={scan_stats.get('skipped_count', 0)}"
                f" ranked={scan_stats.get('ranked_long', 0)}/{scan_stats.get('ranked_short', 0)}"
                f" actionable={scan_stats.get('long_actionable', 0)}/{scan_stats.get('short_actionable', 0)}"
                f" ms={scan_stats.get('duration_ms', 0)}"
            )
        agent_summary = ""
        agent_payload = result.get("agent_pipeline")
        if isinstance(agent_payload, dict) and agent_payload.get("enabled"):
            agent_sum = agent_payload.get("summary") if isinstance(agent_payload.get("summary"), dict) else {}
            filters = agent_sum.get("entry_filter_counts") if isinstance(agent_sum.get("entry_filter_counts"), dict) else {}
            agent_summary = (
                f" | agent in={agent_sum.get('scanner_results_in', 0)}"
                f" directional={agent_sum.get('candidates_directional', 0)}"
                f" evaluated={agent_sum.get('entry_evaluations', 0)}"
                f" entry_skip={agent_sum.get('entry_skipped', 0)}"
                f" monitor={agent_sum.get('positions_monitored', 0)}/{agent_sum.get('positions_received', 0)}"
            )
            if filters:
                agent_summary += f" filters={filters}"
        print(
            f"{datetime.now(tz=UTC).isoformat()} | "
            + ", ".join(summary)
            + paper_summary
            + live_summary
            + scan_summary
            + agent_summary
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
