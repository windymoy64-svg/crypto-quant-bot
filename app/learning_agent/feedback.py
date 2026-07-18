"""Convert completed position outcomes into Learning Agent trade records.

Two builders are exposed:

- ``build_trade_record`` — when the entry and exit ``ChartReading`` objects are
  still in memory (called right after a decision was made).
- ``build_trade_record_from_dicts`` — when we only have serialized observation
  dictionaries loaded from ``ChartObservationStore``.

Both produce the same ``TradeRecord`` schema so the learning journal remains
consistent regardless of which pathway records the trade.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.chart_agent.models import ChartReading
from app.learning_agent.models import TradeOutcome, TradeRecord


def build_trade_record(
    *,
    trade_id: str,
    position: dict[str, Any],
    close_event: dict[str, Any],
    entry_reading: ChartReading,
    exit_reading: ChartReading,
) -> TradeRecord:
    """Build a labeled TradeRecord from a closed paper/live position.

    Supports the current realtime paper event shape and normalized executor
    events. Unknown close reasons remain MANUAL instead of being guessed.
    """
    return _build(
        trade_id=trade_id,
        position=position,
        close_event=close_event,
        entry_context=_context_from_reading(entry_reading),
        exit_context=_context_from_reading(exit_reading),
    )


def build_trade_record_from_dicts(
    *,
    trade_id: str,
    position: dict[str, Any],
    close_event: dict[str, Any],
    entry_observation: dict[str, Any] | None,
    exit_observation: dict[str, Any] | None,
) -> TradeRecord:
    """Build a TradeRecord from serialized ChartObservation dictionaries.

    Falls back to neutral defaults when observations are missing so the record
    remains queryable even if Chart Agent was disabled at entry time.
    """
    return _build(
        trade_id=trade_id,
        position=position,
        close_event=close_event,
        entry_context=_context_from_observation(entry_observation),
        exit_context=_context_from_observation(exit_observation),
    )


def _build(
    *,
    trade_id: str,
    position: dict[str, Any],
    close_event: dict[str, Any],
    entry_context: dict[str, Any],
    exit_context: dict[str, Any],
) -> TradeRecord:
    entry = float(position.get("entry", 0.0))
    nested_position = close_event.get("position") if isinstance(
        close_event.get("position"), dict
    ) else {}
    exit_price = float(
        close_event.get("exit")
        or nested_position.get("exit")
        or close_event.get("price")
        or position.get("exit", 0.0)
    )
    side = _normalize_side(position.get("side"))
    pnl_absolute = float(
        close_event.get("realized_pnl")
        or nested_position.get("realized_pnl")
        or position.get("realized_pnl", 0.0)
    )
    quantity = float(position.get("size") or position.get("quantity") or 0.0)
    cost = entry * quantity
    pnl_percent = (pnl_absolute / cost) * 100 if cost > 0 else _price_return(
        side, entry, exit_price
    )
    close_reason = str(
        close_event.get("close_reason")
        or close_event.get("reason")
        or position.get("close_reason", "")
    )
    take_profit = position.get("take_profit") or []
    if not isinstance(take_profit, list):
        take_profit = []

    return TradeRecord(
        trade_id=trade_id,
        symbol=str(position.get("symbol") or close_event.get("symbol") or ""),
        side=side,
        timestamp_entry=str(position.get("opened_at", "")),
        timestamp_exit=str(
            close_event.get("closed_at")
            or close_event.get("timestamp")
            or position.get("closed_at", "")
        ),
        entry_price=entry,
        exit_price=exit_price,
        stop_loss=float(position.get("static_stop_loss") or position.get("stop_loss") or 0.0),
        take_profit_1=_list_float(take_profit, 0),
        take_profit_2=_list_float(take_profit, 1),
        take_profit_3=_list_float(take_profit, 2),
        outcome=_classify_outcome(close_reason, pnl_percent),
        pnl_percent=round(pnl_percent, 6),
        pnl_absolute=pnl_absolute,
        hold_duration_minutes=_duration_minutes(
            str(position.get("opened_at", "")),
            str(close_event.get("timestamp") or position.get("closed_at", "")),
        ),
        max_favorable_excursion=_excursion(position, favorable=True),
        max_adverse_excursion=_excursion(position, favorable=False),
        regime_at_entry=entry_context["regime"],
        bias_at_entry=entry_context["bias"],
        confluence_at_entry=entry_context["confluence"],
        htf_trend_at_entry=entry_context["htf_trend"],
        patterns_at_entry=list(entry_context["patterns"]),
        techniques_at_entry=list(entry_context["techniques"]),
        key_levels_at_entry=list(entry_context["key_levels"]),
        regime_at_exit=exit_context["regime"],
        bias_at_exit=exit_context["bias"],
        exit_reason_detail=close_reason,
        entry_strategy=str(position.get("strategy", position.get("entry_strategy", ""))),
        entry_confidence=float(position.get("confidence", 0.0)),
        meta={"position": position, "close_event": close_event},
    )


def _context_from_reading(reading: ChartReading) -> dict[str, Any]:
    return {
        "regime": reading.regime,
        "bias": reading.bias,
        "confluence": reading.confluence_score,
        "htf_trend": reading.htf_trend,
        "patterns": [p.name for p in reading.candle_patterns],
        "techniques": list(reading.techniques_used),
        "key_levels": [level.price for level in reading.key_levels],
    }


def _context_from_observation(obs: dict[str, Any] | None) -> dict[str, Any]:
    if not obs:
        return _empty_context()
    reading = obs.get("chart_reading") or {}
    patterns_raw = reading.get("candle_patterns") or []
    patterns = [p.get("name", "") for p in patterns_raw if isinstance(p, dict)]
    key_levels_raw = reading.get("key_levels") or []
    key_levels = [
        float(level.get("price", 0.0))
        for level in key_levels_raw
        if isinstance(level, dict)
    ]
    return {
        "regime": str(reading.get("regime", "MIXED")),
        "bias": str(reading.get("bias", "NEUTRAL")),
        "confluence": float(reading.get("confluence_score", 0.0)),
        "htf_trend": str(reading.get("htf_trend", "SIDE")),
        "patterns": patterns,
        "techniques": [str(t) for t in reading.get("techniques_used") or []],
        "key_levels": key_levels,
    }


def _empty_context() -> dict[str, Any]:
    return {
        "regime": "MIXED",
        "bias": "NEUTRAL",
        "confluence": 0.0,
        "htf_trend": "SIDE",
        "patterns": [],
        "techniques": [],
        "key_levels": [],
    }


def _normalize_side(value: object) -> str:
    return "SELL" if str(value).upper() in {"SELL", "SHORT"} else "BUY"


def _classify_outcome(reason: str, pnl_percent: float) -> TradeOutcome:
    normalized = reason.upper()
    if "TRAIL" in normalized:
        return "TRAILING"
    if "STOP" in normalized or normalized in {"SL", "STOP_LOSS"}:
        return "SL"
    if "TAKE_PROFIT" in normalized or normalized.startswith("TP"):
        return "TP"
    if "INVALID" in normalized or "CISD" in normalized or "CHOCH" in normalized:
        return "INVALIDATION"
    if abs(pnl_percent) < 0.01:
        return "BREAKEVEN"
    return "MANUAL"


def _price_return(side: str, entry: float, exit_price: float) -> float:
    if entry <= 0:
        return 0.0
    move = (exit_price - entry) / entry * 100
    return move if side == "BUY" else -move


def _list_float(values: list[Any], index: int) -> float | None:
    if index >= len(values):
        return None
    return float(values[index])


def _duration_minutes(start: str, end: str) -> float:
    try:
        opened = datetime.fromisoformat(start.replace("Z", "+00:00"))
        closed = datetime.fromisoformat(end.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, (closed - opened).total_seconds() / 60)


def _excursion(position: dict[str, Any], *, favorable: bool) -> float:
    entry = float(position.get("entry", 0.0))
    if entry <= 0:
        return 0.0
    high = float(position.get("highest_price", entry))
    low = float(position.get("lowest_price", entry))
    side = _normalize_side(position.get("side"))
    if side == "BUY":
        price = high if favorable else low
        return (price - entry) / entry * 100
    price = low if favorable else high
    return (entry - price) / entry * 100