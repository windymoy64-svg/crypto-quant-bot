"""ChartProposal — free-form LLM chart analysis contract.

The Chart LLM may use ANY method, technique, or indicator suited to the
market and symbol (SMC, ICT, Wyckoff, Elliott, volume profile, funding
narratives, fib, BB, orderflow stories, coin-specific habits, etc.).

Python still owns deterministic ChartReading, geometry validation, and
refusal to treat the proposal as a final trade decision / order.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from app.chart_agent.models import ChartReading

LtfState = Literal[
    "WAIT_PULLBACK",
    "WAIT_BREAKOUT",
    "IN_ZONE",
    "EXTENDED",
    "CHOP",
    "READY",
    "AVOID",
    "UNKNOWN",
]
SetupStance = Literal["LONG", "SHORT", "WAIT", "AVOID", "NEUTRAL"]

MIN_SL_PCT = 0.35
MAX_SL_PCT = 4.5
MIN_RR = 1.5
MAX_ENTRY_DRIFT_PCT = 3.0

_REJECT_TOKENS = (
    "incomplete",
    "not_below",
    "not_above",
    "sl_too",
    "rr_too",
    "conflicts_reading",
    "entry_drift",
    "not_actionable",
)


@dataclass(frozen=True)
class ChartProposal:
    """Structured free-technique chart analysis from Chart LLM."""

    symbol: str
    stance: SetupStance = "NEUTRAL"
    htf_trend: str = "UNKNOWN"
    mtf_trend: str = "UNKNOWN"
    ltf_state: LtfState | str = "UNKNOWN"
    regime_note: str = ""
    methods_used: list[str] = field(default_factory=list)
    indicators_used: list[str] = field(default_factory=list)
    techniques_used: list[str] = field(default_factory=list)
    support_levels: list[float] = field(default_factory=list)
    resistance_levels: list[float] = field(default_factory=list)
    key_zones: list[dict[str, Any]] = field(default_factory=list)
    indicator_notes: dict[str, Any] = field(default_factory=dict)
    narrative: str = ""
    wait_condition: str = ""
    invalidation_note: str = ""
    proposed_entry: float | None = None
    proposed_sl: float | None = None
    proposed_tp1: float | None = None
    proposed_tp2: float | None = None
    proposed_tp3: float | None = None
    setup_quality: float = 0.0
    reasons: list[str] = field(default_factory=list)
    coin_specific_notes: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def has_full_levels(self) -> bool:
        return (
            self.proposed_entry is not None
            and self.proposed_sl is not None
            and self.proposed_tp1 is not None
            and float(self.proposed_entry) > 0
            and float(self.proposed_sl) > 0
            and float(self.proposed_tp1) > 0
        )


@dataclass(frozen=True)
class ProposalValidation:
    accepted: bool
    reasons: list[str] = field(default_factory=list)
    risk_reward: float = 0.0
    sl_pct: float = 0.0
    aligned_with_reading_bias: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def _as_float_list(value: Any) -> list[float]:
    if not isinstance(value, list):
        return []
    out: list[float] = []
    for item in value:
        number = _as_float(item)
        if number is not None and number > 0:
            out.append(number)
    return out


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            out.append(text)
    return out


def _normalize_stance(raw: Any, bias_hint: str = "") -> SetupStance:
    text = str(raw or bias_hint or "NEUTRAL").strip().upper()
    aliases = {
        "BUY": "LONG",
        "ENTRY_BUY": "LONG",
        "BULLISH": "LONG",
        "LONG": "LONG",
        "SELL": "SHORT",
        "ENTRY_SELL": "SHORT",
        "BEARISH": "SHORT",
        "SHORT": "SHORT",
        "WAIT": "WAIT",
        "HOLD": "WAIT",
        "AVOID": "AVOID",
        "SKIP": "AVOID",
        "NO_TRADE": "AVOID",
        "NEUTRAL": "NEUTRAL",
    }
    mapped = aliases.get(text, "NEUTRAL")
    if mapped in {"LONG", "SHORT", "WAIT", "AVOID", "NEUTRAL"}:
        return mapped  # type: ignore[return-value]
    return "NEUTRAL"


def parse_chart_proposal(
    payload: dict[str, Any] | None,
    *,
    symbol: str,
) -> ChartProposal | None:
    """Parse free-form LLM JSON into ChartProposal. Returns None if empty."""
    if not isinstance(payload, dict) or not payload:
        return None

    data = payload.get("proposal") if isinstance(payload.get("proposal"), dict) else payload

    methods = _as_str_list(
        data.get("methods_used") or data.get("methods") or data.get("analysis_methods")
    )
    indicators = _as_str_list(
        data.get("indicators_used") or data.get("indicators") or data.get("indicator_list")
    )
    techniques = _as_str_list(
        data.get("techniques_used") or data.get("techniques") or data.get("setup_techniques")
    )

    quality = _as_float(data.get("setup_quality") or data.get("confidence") or data.get("quality"))
    if quality is not None and quality <= 1.0:
        quality *= 100.0
    if quality is None:
        quality = 0.0
    quality = max(0.0, min(100.0, quality))

    tps = data.get("proposed_tp") or data.get("take_profits") or data.get("tps")
    tp1 = _as_float(data.get("proposed_tp1") or data.get("tp1"))
    tp2 = _as_float(data.get("proposed_tp2") or data.get("tp2"))
    tp3 = _as_float(data.get("proposed_tp3") or data.get("tp3"))
    if isinstance(tps, list):
        floats = _as_float_list(tps)
        if tp1 is None and len(floats) >= 1:
            tp1 = floats[0]
        if tp2 is None and len(floats) >= 2:
            tp2 = floats[1]
        if tp3 is None and len(floats) >= 3:
            tp3 = floats[2]

    zones = data.get("key_zones") or data.get("zones") or []
    if not isinstance(zones, list):
        zones = []
    clean_zones: list[dict[str, Any]] = [z for z in zones if isinstance(z, dict)]

    notes = data.get("indicator_notes") or data.get("indicators_note") or {}
    if not isinstance(notes, dict):
        notes = {"note": str(notes)}

    narrative = str(
        data.get("narrative") or data.get("summary") or data.get("analysis") or ""
    ).strip()
    reasons = _as_str_list(data.get("reasons") or data.get("reason_codes"))

    return ChartProposal(
        symbol=symbol,
        stance=_normalize_stance(data.get("stance") or data.get("bias") or data.get("direction")),
        htf_trend=str(data.get("htf_trend") or data.get("htf") or "UNKNOWN"),
        mtf_trend=str(data.get("mtf_trend") or data.get("mtf") or "UNKNOWN"),
        ltf_state=str(data.get("ltf_state") or data.get("ltf") or "UNKNOWN"),
        regime_note=str(data.get("regime_note") or data.get("regime") or ""),
        methods_used=methods,
        indicators_used=indicators,
        techniques_used=techniques,
        support_levels=_as_float_list(data.get("support_levels") or data.get("supports")),
        resistance_levels=_as_float_list(data.get("resistance_levels") or data.get("resistances")),
        key_zones=clean_zones,
        indicator_notes=notes,
        narrative=narrative,
        wait_condition=str(data.get("wait_condition") or data.get("wait") or ""),
        invalidation_note=str(data.get("invalidation_note") or data.get("invalidation") or ""),
        proposed_entry=_as_float(data.get("proposed_entry") or data.get("entry")),
        proposed_sl=_as_float(data.get("proposed_sl") or data.get("stop_loss") or data.get("sl")),
        proposed_tp1=tp1,
        proposed_tp2=tp2,
        proposed_tp3=tp3,
        setup_quality=round(quality, 1),
        reasons=reasons,
        coin_specific_notes=_as_str_list(
            data.get("coin_specific_notes") or data.get("symbol_notes")
        ),
        raw=dict(payload),
    )


def validate_chart_proposal(
    proposal: ChartProposal,
    reading: ChartReading,
    *,
    min_rr: float = MIN_RR,
    min_sl_pct: float = MIN_SL_PCT,
    max_sl_pct: float = MAX_SL_PCT,
) -> ProposalValidation:
    """Validate proposed levels; free-form method names are never rejected."""
    reasons: list[str] = []

    if proposal.stance in {"WAIT", "AVOID", "NEUTRAL"}:
        reasons.append(f"stance_{proposal.stance.lower()}_not_actionable")
        return ProposalValidation(accepted=False, reasons=reasons)

    if not proposal.has_full_levels:
        reasons.append("incomplete_levels")
        return ProposalValidation(accepted=False, reasons=reasons)

    entry = float(proposal.proposed_entry)  # type: ignore[arg-type]
    sl = float(proposal.proposed_sl)  # type: ignore[arg-type]
    tp1 = float(proposal.proposed_tp1)  # type: ignore[arg-type]

    if proposal.stance == "LONG":
        if sl >= entry:
            reasons.append("long_sl_not_below_entry")
        if tp1 <= entry:
            reasons.append("long_tp_not_above_entry")
    else:
        if sl <= entry:
            reasons.append("short_sl_not_above_entry")
        if tp1 >= entry:
            reasons.append("short_tp_not_below_entry")

    risk = abs(entry - sl)
    sl_pct = (risk / entry) * 100.0 if entry > 0 else 0.0
    if sl_pct < min_sl_pct:
        reasons.append(f"sl_too_tight={sl_pct:.2f}%")
    if sl_pct > max_sl_pct:
        reasons.append(f"sl_too_wide={sl_pct:.2f}%")

    rr = abs(tp1 - entry) / risk if risk > 0 else 0.0
    if rr < min_rr:
        reasons.append(f"rr_too_low={rr:.2f}")

    aligned = False
    if reading.bias == "BULLISH" and proposal.stance == "LONG":
        aligned = True
    elif reading.bias == "BEARISH" and proposal.stance == "SHORT":
        aligned = True
    elif reading.bias == "NEUTRAL":
        aligned = True
        reasons.append("reading_bias_neutral")
    else:
        reasons.append(
            f"stance_conflicts_reading_bias={proposal.stance}_vs_{reading.bias}"
        )

    if reading.entry_zone and entry > 0:
        mid = (reading.entry_zone[0] + reading.entry_zone[1]) / 2.0
        if mid > 0:
            drift = abs(entry - mid) / mid * 100.0
            if drift > MAX_ENTRY_DRIFT_PCT:
                reasons.append(f"entry_drift_from_python_zone={drift:.2f}%")

    accepted = not any(any(tok in r for tok in _REJECT_TOKENS) for r in reasons)

    return ProposalValidation(
        accepted=accepted,
        reasons=reasons,
        risk_reward=round(rr, 2),
        sl_pct=round(sl_pct, 3),
        aligned_with_reading_bias=aligned,
    )


def proposal_system_prompt() -> str:
    """System prompt: free techniques, structured JSON only, no orders."""
    return (
        "You are the Chart Analysis Agent for a crypto trading bot. "
        "You may use ANY analysis method, technique, or indicator that fits "
        "this market regime and this specific coin "
        "(examples only — not a limit: market structure, BOS/CHoCH, FVG, order blocks, "
        "liquidity sweeps, Wyckoff, Elliott, volume profile, VWAP, Bollinger, Fibonacci, "
        "EMA/SMA stacks, RSI/MACD divergences, candle psychology, session opens, "
        "funding/OI narratives if present in context, coin-specific behavior). "
        "Choose freely what is relevant; do not force a fixed indicator set. "
        "You PROPOSE analysis and optional levels only. You do NOT place orders. "
        "You do NOT override deterministic engine fields; your output is advisory. "
        "Return a single JSON object with keys: "
        "stance (LONG|SHORT|WAIT|AVOID|NEUTRAL), "
        "htf_trend, mtf_trend, ltf_state, regime_note, "
        "methods_used (array of strings — open vocabulary), "
        "indicators_used (array — open vocabulary), "
        "techniques_used (array — open vocabulary), "
        "support_levels, resistance_levels, key_zones, indicator_notes, "
        "narrative, wait_condition, invalidation_note, "
        "proposed_entry, proposed_sl, proposed_tp1, proposed_tp2, proposed_tp3, "
        "setup_quality (0-100), reasons (array), coin_specific_notes (array). "
        "If waiting or avoiding, set stance WAIT/AVOID and levels null. "
        "Output JSON only."
    )


def proposal_user_payload(reading: ChartReading, *, stage: str) -> dict[str, Any]:
    return {
        "stage": stage,
        "symbol": reading.symbol,
        "deterministic_chart_reading": reading.to_dict(),
        "instructions": (
            "Using the deterministic reading as factual market snapshot, "
            "produce a free-technique multi-timeframe analysis. "
            "You may introduce methods/indicators not listed in technique_signals "
            "if they fit this coin and regime. "
            "Propose entry/SL/TP only when stance is LONG or SHORT. "
            "Prefer levels consistent with supports/resistances and invalidation "
            "already present when possible."
        ),
    }
