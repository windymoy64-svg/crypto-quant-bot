"""Bridge between the existing realtime scanner and the multi-agent coordinator.

Runs the coordinator on qualified scanner candidates and open positions,
writing results to an audit artifact. Never mutates paper/live state by itself.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from app.agent_pipeline.coordinator import (
    AgentPipelineConfig,
    AgentPipelineCoordinator,
)
from app.agent_pipeline.models import ScannerCandidate
from app.core.models import Candle
from app.events.events import EntryCandidateProcessed
from app.events.publisher import publish
from app.executor_agent.models import PositionContext
from app.market.data_service import MarketDataService


@dataclass(frozen=True)
class CandleFetchResult:
    """Candle fetch outcome; errors must not masquerade as empty data."""

    candles: list[Candle]
    status: Literal["ok", "empty", "error"]
    error_type: str | None = None


def _classify_fetch_error(exc: Exception) -> str:
    text = f"{exc.__class__.__name__} {exc}".lower()
    if "timeout" in text:
        return "timeout"
    if any(token in text for token in ("ratelimit", "rate_limit", "429")):
        return "rate_limited"
    if any(token in text for token in ("connection", "network", "http")):
        return "transport"
    return "provider_error"


def _parse_conflict_policy(value: object) -> str:
    policy = str(value or "REJECT").strip().upper()
    if policy not in {"REJECT", "WATCH", "IGNORE"}:
        raise ValueError(f"Invalid scanner_chart_conflict_policy: {policy}")
    return policy


def _canonical_symbol(value: object) -> str:
    """Normalize Bitunix compact symbols and slash/dash variants."""

    symbol = str(value or "").strip().upper().replace("-", "/")
    if "/" not in symbol and symbol.endswith("USDT") and len(symbol) > 4:
        symbol = f"{symbol[:-4]}/USDT"
    return symbol


@dataclass(frozen=True)
class AgentPipelineRuntimeConfig:
    """Runtime configuration for the pipeline bridge.

    Live orders require ALL of:
    - enabled
    - execute_decisions
    - allow_live_orders
    - executor.live
    - risk gate approval
    """

    enabled: bool = False
    execute_decisions: bool = False
    allow_live_orders: bool = False
    min_scanner_confidence: float = 90.0
    min_hold_seconds: float = 300.0
    htf_timeframe: str = "4h"
    mtf_timeframe: str = "1h"
    ltf_timeframe: str = "15m"
    htf_limit: int = 200
    mtf_limit: int = 200
    ltf_limit: int = 200
    output_path: str = "logs/agent_pipeline.json"
    max_entry_symbols: int = 5
    monitor_positions: bool = True
    # Soft-entry for WATCH: Chart/Decision may still HOLD/SKIP; not auto-buy.
    allow_watch_soft_entry: bool = False
    min_watch_confidence: float = 75.0
    max_watch_soft_entry: int = 3
    # Free-technique Chart LLM proposal + Decision veto (executor remains non-LLM).
    chart_llm_propose: bool = True
    adopt_chart_proposal_levels: bool = False
    decision_llm_can_veto: bool = True
    decision_llm_veto_min_confidence: float = 0.75
    # Learning Journal Coach PolicyPatch (shadow by default).
    apply_llm_policy: bool = False
    policy_min_confidence: float = 0.6
    # Scanner vs deterministic chart bias conflict handling.
    scanner_chart_conflict_policy: str = "REJECT"

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "AgentPipelineRuntimeConfig":
        data = data or {}
        return cls(
            enabled=bool(data.get("enabled", False)),
            execute_decisions=bool(data.get("execute_decisions", False)),
            allow_live_orders=bool(data.get("allow_live_orders", False)),
            min_scanner_confidence=float(data.get("min_scanner_confidence", 90.0)),
            min_hold_seconds=float(data.get("min_hold_seconds", 300.0)),
            htf_timeframe=str(data.get("htf_timeframe", "4h")),
            mtf_timeframe=str(data.get("mtf_timeframe", "1h")),
            ltf_timeframe=str(data.get("ltf_timeframe", "15m")),
            htf_limit=int(data.get("htf_limit", 200)),
            mtf_limit=int(data.get("mtf_limit", 200)),
            ltf_limit=int(data.get("ltf_limit", 200)),
            output_path=str(data.get("output_path", "logs/agent_pipeline.json")),
            max_entry_symbols=int(data.get("max_entry_symbols", 5)),
            monitor_positions=bool(data.get("monitor_positions", True)),
            allow_watch_soft_entry=bool(data.get("allow_watch_soft_entry", False)),
            min_watch_confidence=float(data.get("min_watch_confidence", 75.0)),
            max_watch_soft_entry=int(data.get("max_watch_soft_entry", 3)),
            chart_llm_propose=bool(data.get("chart_llm_propose", True)),
            adopt_chart_proposal_levels=bool(data.get("adopt_chart_proposal_levels", False)),
            decision_llm_can_veto=bool(data.get("decision_llm_can_veto", True)),
            decision_llm_veto_min_confidence=float(
                data.get("decision_llm_veto_min_confidence", 0.75)
            ),
            apply_llm_policy=bool(data.get("apply_llm_policy", False)),
            policy_min_confidence=float(data.get("policy_min_confidence", 0.6)),
            scanner_chart_conflict_policy=_parse_conflict_policy(
                data.get("scanner_chart_conflict_policy", "REJECT")
            ),
        )


def _candle_fetcher(market_data: MarketDataService, timeframe: str, limit: int):
    def _fetch(symbol: str) -> CandleFetchResult:
        try:
            loaded = market_data.fetch_ohlcv(symbol=symbol, timeframe=timeframe, limit=limit)
            candles = list(loaded.candles)
            return CandleFetchResult(candles, "ok" if candles else "empty")
        except Exception as exc:  # noqa: BLE001 - classify and fail closed at caller
            return CandleFetchResult([], "error", _classify_fetch_error(exc))
    return _fetch


def _to_candidate(raw_item: dict[str, Any]) -> ScannerCandidate:
    short_action = str(raw_item.get("short_action") or "").upper()
    long_action = str(raw_item.get("action") or "SKIP").upper()
    meta: dict[str, Any] = dict(raw_item.get("meta") or raw_item.get("short_meta") or {})
    action_raw = long_action
    conf = float(raw_item.get("confidence") or 0.0)
    gates = list(raw_item.get("failed_gates") or [])
    source = "long"
    if short_action in {"SELL", "BUY", "WATCH", "SKIP"} and long_action not in {"BUY", "SELL"}:
        conf = float(raw_item.get("short_confidence") or conf or 0.0)
        short_gates = raw_item.get("short_failed_gates")
        gates = list(short_gates) if isinstance(short_gates, list) else gates
        source = "short"
        if short_action in {"SELL", "BUY"}:
            action_raw = "SELL"
            meta["position_side"] = "SHORT"
            meta["order_side"] = "SELL"
            meta["short_action_raw"] = short_action
            meta["intent"] = "OPEN"
        else:
            action_raw = short_action
    else:
        if short_action == "SELL":
            short_conf = float(raw_item.get("short_confidence") or 0.0)
            if long_action not in {"BUY", "SELL"} or short_conf >= conf:
                action_raw = "SELL"
                conf = short_conf if short_conf else conf
                short_gates = raw_item.get("short_failed_gates")
                if isinstance(short_gates, list):
                    gates = list(short_gates)
                source = "short"
                meta["position_side"] = "SHORT"
                meta["order_side"] = "SELL"
                meta["short_action_raw"] = short_action
                meta["intent"] = "OPEN"
        elif long_action == "BUY":
            meta.setdefault("position_side", "LONG")
            meta.setdefault("order_side", "BUY")
            meta.setdefault("intent", "OPEN")
            source = "long"
    meta["candidate_source"] = source
    action = action_raw if action_raw in {"BUY", "SELL", "WATCH", "SKIP"} else "SKIP"
    return ScannerCandidate(
        symbol=str(raw_item.get("symbol", "")),
        action=cast(Literal["BUY", "SELL", "WATCH", "SKIP"], action),
        confidence=conf,
        failed_gates=[str(g) for g in gates],
        meta=meta,
    )

def _position_context(raw: dict[str, Any]) -> PositionContext | None:
    side = str(raw.get("side", "BUY")).upper()
    normalized: Literal["BUY", "SELL"] = "SELL" if side in {"SELL", "SHORT"} else "BUY"
    quantity = float(raw.get("remaining_size") or raw.get("size") or 0.0)
    if quantity <= 0:
        return None
    return PositionContext(
        side=normalized,
        quantity=quantity,
        current_price=float(raw.get("last_price") or raw.get("current_price") or 0.0) or None,
        position_id=str(raw.get("position_id") or raw.get("id") or "") or None,
        entry_price=float(raw.get("entry_price") or raw.get("entry") or 0.0) or None,
        stop_loss=float(raw.get("stop_loss") or 0.0) or None,
        take_profit=float(raw.get("take_profit") or 0.0) or None,
        leverage=float(raw.get("leverage") or 0.0) or None,
        lifecycle_version=str(raw.get("lifecycle_version") or "") or None,
    )

def _write_output(
    path: str, payload: dict[str, Any], *, append_history: bool = True,
) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2)
    temporary.replace(output)
    if not append_history:
        return
    history = (
        output.with_name(output.stem + "_history.jsonl")
        if output.suffix == ".json"
        else output.parent / "agent_pipeline_history.jsonl"
    )
    event = {
        "generated_at": payload.get("generated_at"),
        "execute_decisions": payload.get("execute_decisions"),
        "executor_mode": payload.get("executor_mode"),
        "live_ready": payload.get("live_ready"),
        "summary": payload.get("summary"),
        "entry_count": len(payload.get("entries") or []),
        "monitor_count": len(payload.get("monitor") or []),
    }
    with history.open("a", encoding="utf-8") as file:
        file.write(json.dumps(event, ensure_ascii=False) + "\n")

def run_pipeline_bridge(
    *,
    config: AgentPipelineRuntimeConfig,
    scanner_results: list[dict[str, Any]],
    open_positions: dict[str, dict[str, Any]],
    pending_entry_symbols: set[str] | None = None,
    market_data: MarketDataService,
    coordinator: AgentPipelineCoordinator | None = None,
) -> dict[str, Any]:
    """Run multi-agent pipeline on scanner output and open positions."""
    if not config.enabled:
        return {"enabled": False, "reason": "pipeline_disabled_by_config"}

    if coordinator is None:
        from app.learning_agent.agent import LearningAgent
        from app.llm.factory import build_agent_llm

        chart_llm_client, chart_llm_model, chart_llm_base_url = build_agent_llm("chart")
        llm_client, llm_model, llm_base_url = build_agent_llm("learning")
        decision_llm_client, decision_llm_model, decision_llm_base_url = build_agent_llm("decision")
        executor_llm_client, executor_llm_model, executor_llm_base_url = build_agent_llm("executor")
        coordinator = AgentPipelineCoordinator(
            learning_agent=LearningAgent(
                llm_client=llm_client, llm_model=llm_model, llm_base_url=llm_base_url
            ),
            chart_llm_client=chart_llm_client,
            chart_llm_model=chart_llm_model,
            chart_llm_base_url=chart_llm_base_url,
            decision_llm_client=decision_llm_client,
            decision_llm_model=decision_llm_model,
            decision_llm_base_url=decision_llm_base_url,
            executor_llm_client=executor_llm_client,
            executor_llm_model=executor_llm_model,
            executor_llm_base_url=executor_llm_base_url,
            config=AgentPipelineConfig(
                min_scanner_confidence=config.min_scanner_confidence,
                execute_decisions=config.execute_decisions,
                allow_watch_soft_entry=config.allow_watch_soft_entry,
                min_watch_confidence=config.min_watch_confidence,
                chart_llm_propose=config.chart_llm_propose,
                adopt_chart_proposal_levels=config.adopt_chart_proposal_levels,
                decision_llm_can_veto=config.decision_llm_can_veto,
                decision_llm_veto_min_confidence=config.decision_llm_veto_min_confidence,
                apply_llm_policy=config.apply_llm_policy,
                policy_min_confidence=config.policy_min_confidence,
                scanner_chart_conflict_policy=config.scanner_chart_conflict_policy,
            ),
        )

    executor_live = bool(getattr(coordinator.executor_agent, "live", False))
    if executor_live and not config.allow_live_orders:
        coordinator.executor_agent.live = False
        executor_live = False
    parity_verified = bool(
        getattr(coordinator.executor_agent, "paper_parity_verified", not executor_live)
    )
    live_ready = bool(
        config.execute_decisions
        and config.allow_live_orders
        and executor_live
        and parity_verified
    )
    live_blocker = (
        "paper_parity_incomplete" if executor_live and not parity_verified else None
    )
    readiness_reason = getattr(
        coordinator.executor_agent, "live_readiness_reason", "ready"
    )
    if executor_live and not parity_verified:
        live_blocker = "paper_parity_incomplete"
    elif executor_live and readiness_reason != "ready":
        live_ready = False
        live_blocker = readiness_reason

    fetch_htf = _candle_fetcher(market_data, config.htf_timeframe, config.htf_limit)
    fetch_mtf = _candle_fetcher(market_data, config.mtf_timeframe, config.mtf_limit)
    fetch_ltf = _candle_fetcher(market_data, config.ltf_timeframe, config.ltf_limit)

    entries: list[dict[str, Any]] = []
    pending_symbols = {
        _canonical_symbol(symbol)
        for symbol in (pending_entry_symbols or set())
        if str(symbol).strip()
    }
    filter_counts: Counter[str] = Counter()
    candidates_seen = 0
    candidates_directional = 0
    candidates_watch = 0
    scanned = 0
    watch_evaluated = 0

    cycle_started_at = datetime.now(tz=UTC).isoformat()

    def _write_progress() -> None:
        """Expose accepted scanner candidates while agents are still working."""

        _write_output(config.output_path, {
            "enabled": True,
            "generated_at": datetime.now(tz=UTC).isoformat(),
            "cycle_started_at": cycle_started_at,
            "processing": True,
            "execute_decisions": config.execute_decisions,
            "allow_live_orders": config.allow_live_orders,
            "executor_mode": "live" if executor_live else "dry_run",
            "live_ready": live_ready,
            "live_blocker": live_blocker,
            "entries": entries,
            "monitor": [],
            "summary": {
                "scanner_results_in": len(scanner_results),
                "candidates_seen": candidates_seen,
                "candidates_directional": candidates_directional,
                "candidates_watch": candidates_watch,
                "entry_filter_counts": dict(filter_counts),
            },
        }, append_history=False)

    hard_candidates: list[ScannerCandidate] = []
    soft_candidates: list[ScannerCandidate] = []
    for raw in scanner_results:
        candidates_seen += 1
        candidate = _to_candidate(raw)
        if candidate.action in {"BUY", "SELL"}:
            candidates_directional += 1
            hard_candidates.append(candidate)
        elif candidate.action == "WATCH":
            candidates_watch += 1
            soft_candidates.append(candidate)
        else:
            filter_counts[f"action_{candidate.action or 'EMPTY'}"] += 1

    hard_candidates.sort(key=lambda c: c.confidence, reverse=True)
    soft_candidates.sort(key=lambda c: c.confidence, reverse=True)

    preview_candidates: list[tuple[ScannerCandidate, bool]] = []
    for candidate in hard_candidates:
        if len(preview_candidates) >= config.max_entry_symbols:
            break
        if (
            candidate.confidence >= config.min_scanner_confidence
            and not candidate.failed_gates
            and _canonical_symbol(candidate.symbol) not in pending_symbols
        ):
            preview_candidates.append((candidate, False))
    if config.allow_watch_soft_entry:
        soft_slots = min(
            config.max_watch_soft_entry,
            max(0, config.max_entry_symbols - len(preview_candidates)),
        )
        for candidate in soft_candidates:
            if sum(1 for _, soft in preview_candidates if soft) >= soft_slots:
                break
            if (
                candidate.confidence >= config.min_watch_confidence
                and not candidate.failed_gates
                and _canonical_symbol(candidate.symbol) not in pending_symbols
            ):
                preview_candidates.append((candidate, True))

    preview_at = datetime.now(tz=UTC).isoformat()
    entries.extend({
        "symbol": candidate.symbol,
        "scanner_confidence": candidate.confidence,
        "scanner_action": candidate.action,
        "soft_entry": soft,
        "processing": True,
        "status": "PROCESSING",
        "timestamp": preview_at,
    } for candidate, soft in preview_candidates)
    if entries:
        filter_counts["processing"] = len(entries)
        _write_progress()

    def _evaluate(candidate: ScannerCandidate, *, soft: bool) -> None:
        nonlocal scanned, watch_evaluated
        if scanned >= config.max_entry_symbols:
            filter_counts["max_entry_symbols_cap"] += 1
            return
        if soft and watch_evaluated >= config.max_watch_soft_entry:
            filter_counts["max_watch_soft_entry_cap"] += 1
            return

        min_conf = (
            config.min_watch_confidence if soft else config.min_scanner_confidence
        )
        if candidate.confidence < min_conf:
            filter_counts["low_confidence" if not soft else "watch_low_confidence"] += 1
            return
        if candidate.failed_gates:
            filter_counts["failed_gates"] += 1
            return
        if _canonical_symbol(candidate.symbol) in pending_symbols:
            filter_counts["pending_entry_exists"] += 1
            entries.append({
                "symbol": candidate.symbol,
                "skipped": True,
                "reason": "pending_entry_exists",
                "soft_entry": soft,
                "scanner_action": candidate.action,
            })
            return

        processing_record = next(
            (
                item for item in entries
                if item.get("processing") and item.get("symbol") == candidate.symbol
            ),
            None,
        )
        if processing_record is None:
            processing_record = {
                "symbol": candidate.symbol,
                "scanner_confidence": candidate.confidence,
                "scanner_action": candidate.action,
                "soft_entry": soft,
                "processing": True,
                "status": "PROCESSING",
                "timestamp": datetime.now(tz=UTC).isoformat(),
            }
            entries.append(processing_record)
            filter_counts["processing"] += 1
            _write_progress()

        fetched = {
            "htf": fetch_htf(candidate.symbol),
            "mtf": fetch_mtf(candidate.symbol),
            "ltf": fetch_ltf(candidate.symbol),
        }
        failed = {name: item for name, item in fetched.items() if item.status != "ok"}
        if failed:
            reason = (
                "candle_fetch_error"
                if any(item.status == "error" for item in failed.values())
                else "missing_multi_timeframe_candles"
            )
            filter_counts[reason] += 1
            processing_record.clear()
            processing_record.update({
                "symbol": candidate.symbol,
                "skipped": True,
                "reason": reason,
                "data_quality": {
                    name: {"status": item.status, "error_type": item.error_type}
                    for name, item in failed.items()
                },
                "soft_entry": soft,
                "scanner_action": candidate.action,
                "timestamp": datetime.now(tz=UTC).isoformat(),
            })
            filter_counts["processing"] -= 1
            _write_progress()
            return

        result = coordinator.process_entry_candidate(
            candidate,
            htf_candles=fetched["htf"].candles,
            mtf_candles=fetched["mtf"].candles,
            ltf_candles=fetched["ltf"].candles,
        )
        entry_record = {
            "symbol": candidate.symbol,
            "scanner_confidence": candidate.confidence,
            "scanner_action": candidate.action,
            "soft_entry": soft,
            "result": result.to_dict(),
        }
        filter_counts["processing"] -= 1
        scanned += 1
        if soft:
            watch_evaluated += 1
            filter_counts["watch_soft_evaluated"] += 1
        else:
            filter_counts["evaluated"] += 1
        try:
            publish(EntryCandidateProcessed(
                symbol=candidate.symbol,
                scanner_confidence=candidate.confidence,
                scanner_action=candidate.action,
                soft_entry=soft,
                result=result.to_dict(),
                timestamp=datetime.now(tz=UTC).isoformat(),
            ))
            entry_record["publish_status"] = "published"
            filter_counts["events_published"] += 1
        except Exception as exc:  # noqa: BLE001 - event failure must not stop trading loop
            entry_record["publish_status"] = "failed"
            entry_record["publish_error_type"] = exc.__class__.__name__
            filter_counts["event_publish_failed"] += 1
            print(
                f"agent_pipeline event publish failed symbol={candidate.symbol} "
                f"error_type={exc.__class__.__name__}",
                flush=True,
            )
        processing_record.clear()
        processing_record.update(entry_record)
        processing_record["timestamp"] = datetime.now(tz=UTC).isoformat()
        _write_progress()

    for candidate in hard_candidates:
        if scanned >= config.max_entry_symbols:
            filter_counts["not_evaluated_after_cap"] += 1
            break
        _evaluate(candidate, soft=False)

    if config.allow_watch_soft_entry:
        for candidate in soft_candidates:
            if scanned >= config.max_entry_symbols:
                filter_counts["not_evaluated_after_cap"] += 1
                break
            if watch_evaluated >= config.max_watch_soft_entry:
                filter_counts["max_watch_soft_entry_cap"] += max(
                    0, len(soft_candidates) - watch_evaluated - filter_counts.get("watch_low_confidence", 0)
                )
                # Cap hit: stop soft evaluations
                break
            _evaluate(candidate, soft=True)
    else:
        if soft_candidates:
            filter_counts["action_WATCH"] += len(soft_candidates)

    monitor: list[dict[str, Any]] = []
    monitor_skipped = 0
    if config.monitor_positions:
        for symbol, raw_position in open_positions.items():
            position = _position_context(raw_position)
            if position is None:
                monitor_skipped += 1
                continue
            fetched = {
                "htf": fetch_htf(symbol),
                "mtf": fetch_mtf(symbol),
                "ltf": fetch_ltf(symbol),
            }
            failed = {name: item for name, item in fetched.items() if item.status != "ok"}
            if failed:
                monitor_skipped += 1
                reason = (
                    "candle_fetch_error"
                    if any(item.status == "error" for item in failed.values())
                    else "missing_multi_timeframe_candles"
                )
                monitor.append({
                    "symbol": symbol,
                    "skipped": True,
                    "reason": reason,
                    "data_quality": {
                        name: {"status": item.status, "error_type": item.error_type}
                        for name, item in failed.items()
                    },
                })
                continue
            result = coordinator.monitor_position(
                symbol=symbol,
                position=position,
                htf_candles=fetched["htf"].candles,
                mtf_candles=fetched["mtf"].candles,
                ltf_candles=fetched["ltf"].candles,
            )
            monitor.append({"symbol": symbol, "result": result.to_dict()})

    entry_skipped = sum(
        1 for item in entries if isinstance(item, dict) and item.get("skipped")
    )
    entry_evaluated = len(entries) - entry_skipped
    summary = {
        "scanner_results_in": len(scanner_results),
        "candidates_seen": candidates_seen,
        "candidates_directional": candidates_directional,
        "candidates_watch": candidates_watch,
        "entry_evaluations": entry_evaluated,
        "entry_skipped": entry_skipped,
        "watch_soft_evaluated": watch_evaluated,
        "entry_filter_counts": dict(filter_counts),
        "min_scanner_confidence": config.min_scanner_confidence,
        "min_watch_confidence": config.min_watch_confidence,
        "allow_watch_soft_entry": config.allow_watch_soft_entry,
        "max_entry_symbols": config.max_entry_symbols,
        "max_watch_soft_entry": config.max_watch_soft_entry,
        "positions_received": len(open_positions),
        "positions_monitored": len(monitor) - sum(
            1 for item in monitor if isinstance(item, dict) and item.get("skipped")
        ),
        "positions_skipped": monitor_skipped,
        "position_symbols": list(open_positions),
        "pending_entry_symbols": sorted(pending_symbols),
    }
    print(
        "agent_pipeline"
        f" in={summary['scanner_results_in']}"
        f" directional={candidates_directional}"
        f" watch={candidates_watch}"
        f" evaluated={entry_evaluated}"
        f" watch_soft={watch_evaluated}"
        f" entry_skip={entry_skipped}"
        f" filters={dict(filter_counts)}"
        f" monitor={summary['positions_monitored']}/{len(open_positions)}",
        flush=True,
    )

    payload: dict[str, Any] = {
        "enabled": True,
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "cycle_started_at": cycle_started_at,
        "processing": False,
        "execute_decisions": config.execute_decisions,
        "allow_live_orders": config.allow_live_orders,
        "executor_mode": "live" if executor_live else "dry_run",
        "live_ready": live_ready,
        "live_blocker": live_blocker,
        "entries": entries,
        "monitor": monitor,
        "summary": summary,
    }
    _write_output(config.output_path, payload)
    return payload
