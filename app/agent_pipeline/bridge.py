"""Bridge between the existing realtime scanner and the multi-agent coordinator.

Runs the coordinator on qualified scanner candidates and open positions,
writing results to an audit artifact. This module never mutates paper or
live state — it produces an advisory JSON output that the operator can review
before deciding to enable ``execute_decisions``.
"""

from __future__ import annotations

import json
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
from app.executor_agent.models import PositionContext
from app.market.data_service import MarketDataService


@dataclass(frozen=True)
class AgentPipelineRuntimeConfig:
    """Runtime configuration for the pipeline bridge.

    The pipeline is disabled by default. When enabled, it still runs entirely
    read-only unless ``execute_decisions`` is also true.
    """

    enabled: bool = False
    execute_decisions: bool = False
    min_scanner_confidence: float = 90.0
    htf_timeframe: str = "4h"
    mtf_timeframe: str = "1h"
    ltf_timeframe: str = "15m"
    htf_limit: int = 200
    mtf_limit: int = 200
    ltf_limit: int = 200
    output_path: str = "logs/agent_pipeline.json"
    max_entry_symbols: int = 5
    monitor_positions: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "AgentPipelineRuntimeConfig":
        data = data or {}
        return cls(
            enabled=bool(data.get("enabled", False)),
            execute_decisions=bool(data.get("execute_decisions", False)),
            min_scanner_confidence=float(data.get("min_scanner_confidence", 90.0)),
            htf_timeframe=str(data.get("htf_timeframe", "4h")),
            mtf_timeframe=str(data.get("mtf_timeframe", "1h")),
            ltf_timeframe=str(data.get("ltf_timeframe", "15m")),
            htf_limit=int(data.get("htf_limit", 200)),
            mtf_limit=int(data.get("mtf_limit", 200)),
            ltf_limit=int(data.get("ltf_limit", 200)),
            output_path=str(data.get("output_path", "logs/agent_pipeline.json")),
            max_entry_symbols=int(data.get("max_entry_symbols", 5)),
            monitor_positions=bool(data.get("monitor_positions", True)),
        )


def _candle_fetcher(
    market_data: MarketDataService,
    timeframe: str,
    limit: int,
):
    def _fetch(symbol: str) -> list[Candle]:
        try:
            loaded = market_data.fetch_ohlcv(
                symbol=symbol, timeframe=timeframe, limit=limit
            )
            return list(loaded.candles)
        except Exception:
            return []
    return _fetch


def _scanner_action(raw_item: dict[str, Any]) -> Literal["BUY", "SELL", "WATCH", "SKIP"]:
    action = str(raw_item.get("action", "SKIP")).upper()
    if action not in {"BUY", "SELL", "WATCH", "SKIP"}:
        return "SKIP"
    return cast(Literal["BUY", "SELL", "WATCH", "SKIP"], action)


def _to_candidate(raw_item: dict[str, Any]) -> ScannerCandidate:
    return ScannerCandidate(
        symbol=str(raw_item.get("symbol", "")),
        action=_scanner_action(raw_item),
        confidence=float(raw_item.get("confidence", 0.0)),
        failed_gates=[str(g) for g in raw_item.get("failed_gates", []) or []],
        meta=raw_item.get("meta") or {},
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
        current_price=float(raw.get("last_price") or raw.get("entry") or 0.0) or None,
        position_id=(
            str(raw.get("position_id") or raw.get("positionId") or "").strip()
            or None
        ),
    )


def _write_output(path: str, payload: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2)


def run_pipeline_bridge(
    *,
    config: AgentPipelineRuntimeConfig,
    scanner_results: list[dict[str, Any]],
    open_positions: dict[str, dict[str, Any]],
    market_data: MarketDataService,
    coordinator: AgentPipelineCoordinator | None = None,
) -> dict[str, Any]:
    """Run the multi-agent pipeline on scanner output and open positions.

    Returns an audit payload describing every entry evaluation and every
    monitored position, then persists it to ``config.output_path``.
    Never triggers real orders unless ``config.execute_decisions`` is true.
    """
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
                llm_client=llm_client,
                llm_model=llm_model,
                llm_base_url=llm_base_url,
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
            ),
        )

    fetch_htf = _candle_fetcher(market_data, config.htf_timeframe, config.htf_limit)
    fetch_mtf = _candle_fetcher(market_data, config.mtf_timeframe, config.mtf_limit)
    fetch_ltf = _candle_fetcher(market_data, config.ltf_timeframe, config.ltf_limit)

    # Process entry candidates. Coordinator filters out low-confidence ones.
    entries: list[dict[str, Any]] = []
    scanned = 0
    for raw in scanner_results:
        if scanned >= config.max_entry_symbols:
            break
        candidate = _to_candidate(raw)
        if candidate.action not in {"BUY", "SELL"}:
            continue
        if candidate.confidence < config.min_scanner_confidence:
            continue
        if candidate.failed_gates:
            continue

        htf = fetch_htf(candidate.symbol)
        mtf = fetch_mtf(candidate.symbol)
        ltf = fetch_ltf(candidate.symbol)
        if not htf or not mtf or not ltf:
            entries.append({
                "symbol": candidate.symbol,
                "skipped": True,
                "reason": "missing_multi_timeframe_candles",
            })
            continue

        result = coordinator.process_entry_candidate(
            candidate, htf_candles=htf, mtf_candles=mtf, ltf_candles=ltf,
        )
        entries.append({
            "symbol": candidate.symbol,
            "scanner_confidence": candidate.confidence,
            "result": result.to_dict(),
        })
        scanned += 1

    # Monitor open positions.
    monitor: list[dict[str, Any]] = []
    if config.monitor_positions:
        for symbol, raw_position in open_positions.items():
            position = _position_context(raw_position)
            if position is None:
                continue
            htf = fetch_htf(symbol)
            mtf = fetch_mtf(symbol)
            ltf = fetch_ltf(symbol)
            if not htf or not mtf or not ltf:
                monitor.append({
                    "symbol": symbol,
                    "skipped": True,
                    "reason": "missing_multi_timeframe_candles",
                })
                continue
            result = coordinator.monitor_position(
                symbol=symbol,
                position=position,
                htf_candles=htf,
                mtf_candles=mtf,
                ltf_candles=ltf,
            )
            monitor.append({
                "symbol": symbol,
                "result": result.to_dict(),
            })

    payload: dict[str, Any] = {
        "enabled": True,
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "execute_decisions": config.execute_decisions,
        "executor_mode": (
            "live" if coordinator.executor_agent.live else "dry_run"
        ),
        "entries": entries,
        "monitor": monitor,
    }

    _write_output(config.output_path, payload)
    return payload
