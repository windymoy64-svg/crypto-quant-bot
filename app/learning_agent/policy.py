"""PolicyPatch — Learning "Journal Coach" advisory that tunes Decision gates.

The Learning LLM reads deterministic trade statistics + recent journal and
proposes a bounded PolicyPatch (JSON). Python validates and CLAMPS every field
before it can influence Decision. Default is SHADOW (log only, no effect) until
enough samples and explicit opt-in.

Never sets buy/sell directly. Only nudges thresholds / filters / size.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# Hard clamps — LLM can never exceed these.
MAX_MIN_CONFLUENCE_DELTA = 15.0
MIN_MIN_CONFLUENCE_DELTA = -5.0
MIN_SIZE_MULT = 0.5
MAX_SIZE_MULT = 1.0
MAX_BLOCK_REGIMES = 3
MAX_PATTERN_LIST = 12
KNOWN_REGIMES = {
    "TRENDING_BULLISH",
    "TRENDING_BEARISH",
    "RANGING",
    "HIGH_VOLATILITY",
    "LOW_VOLATILITY",
    "MIXED",
}


@dataclass(frozen=True)
class PolicyPatch:
    """Bounded, validated policy adjustment for Decision Agent."""

    min_confluence_delta: float = 0.0
    block_regimes: list[str] = field(default_factory=list)
    prefer_patterns: list[str] = field(default_factory=list)
    avoid_patterns: list[str] = field(default_factory=list)
    size_multiplier: float = 1.0
    max_entries_per_cycle: int | None = None
    confidence: float = 0.0
    requires_min_samples: int = 30
    reasons: list[str] = field(default_factory=list)
    human_summary: str = ""
    source: str = "llm_journal_coach"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def is_noop(self) -> bool:
        return (
            self.min_confluence_delta == 0.0
            and not self.block_regimes
            and not self.prefer_patterns
            and not self.avoid_patterns
            and self.size_multiplier == 1.0
            and self.max_entries_per_cycle is None
        )


@dataclass(frozen=True)
class PolicyValidation:
    accepted: bool
    applied: bool
    reasons: list[str] = field(default_factory=list)
    total_trades: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _num(value: Any, default: float = 0.0) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return default
    if n != n:
        return default
    return n


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _str_list(value: Any, cap: int) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            out.append(text)
        if len(out) >= cap:
            break
    return out


def parse_policy_patch(payload: dict[str, Any] | None) -> PolicyPatch | None:
    """Parse LLM JSON into a clamped PolicyPatch. None if empty/invalid."""
    if not isinstance(payload, dict) or not payload:
        return None
    data = payload.get("policy_patch") if isinstance(payload.get("policy_patch"), dict) else payload

    delta = _clamp(
        _num(data.get("min_confluence_delta"), 0.0),
        MIN_MIN_CONFLUENCE_DELTA,
        MAX_MIN_CONFLUENCE_DELTA,
    )
    size_mult = _clamp(_num(data.get("size_multiplier"), 1.0), MIN_SIZE_MULT, MAX_SIZE_MULT)

    block = [r.upper() for r in _str_list(data.get("block_regimes"), MAX_BLOCK_REGIMES)]
    block = [r for r in block if r in KNOWN_REGIMES]

    conf = _num(data.get("confidence"), 0.0)
    if conf > 1.0:
        conf = conf / 100.0
    conf = _clamp(conf, 0.0, 1.0)

    max_entries = data.get("max_entries_per_cycle")
    max_entries_val = None
    if max_entries is not None:
        try:
            max_entries_val = max(0, int(max_entries))
        except (TypeError, ValueError):
            max_entries_val = None

    req = data.get("requires_min_samples")
    try:
        req_val = int(req) if req is not None else 30
    except (TypeError, ValueError):
        req_val = 30
    req_val = max(0, req_val)

    return PolicyPatch(
        min_confluence_delta=round(delta, 2),
        block_regimes=block,
        prefer_patterns=_str_list(data.get("prefer_patterns"), MAX_PATTERN_LIST),
        avoid_patterns=_str_list(data.get("avoid_patterns"), MAX_PATTERN_LIST),
        size_multiplier=round(size_mult, 3),
        max_entries_per_cycle=max_entries_val,
        confidence=round(conf, 3),
        requires_min_samples=req_val,
        reasons=_str_list(data.get("reasons") or data.get("reason_codes"), 10),
        human_summary=str(data.get("human_summary") or data.get("summary") or "").strip(),
    )


def validate_policy_patch(
    patch: PolicyPatch,
    *,
    total_trades: int,
    apply_enabled: bool,
    min_confidence: float = 0.6,
) -> PolicyValidation:
    """Decide whether a parsed patch may actually influence Decision."""
    reasons: list[str] = []
    if patch.is_noop:
        reasons.append("noop_patch")
        return PolicyValidation(
            accepted=True, applied=False, reasons=reasons, total_trades=total_trades
        )

    accepted = True
    if patch.confidence < min_confidence:
        reasons.append(f"confidence_below_min={patch.confidence:.2f}<{min_confidence:.2f}")
        accepted = False
    if total_trades < patch.requires_min_samples:
        reasons.append(f"insufficient_samples={total_trades}<{patch.requires_min_samples}")
        accepted = False

    applied = bool(accepted and apply_enabled)
    if accepted and not apply_enabled:
        reasons.append("shadow_mode_not_applied")
    return PolicyValidation(
        accepted=accepted, applied=applied, reasons=reasons, total_trades=total_trades
    )


def policy_system_prompt() -> str:
    return (
        "You are the Learning Journal Coach for a crypto trading bot. "
        "Read ONLY the provided deterministic trade statistics and recent journal. "
        "Propose a BOUNDED policy patch to improve expectancy and reduce drawdown. "
        "You do NOT place trades and do NOT pick individual entries. "
        "You may only nudge: min_confluence_delta (-5..+15), block_regimes "
        "(max 3 known regimes), prefer_patterns, avoid_patterns, "
        "size_multiplier (0.5..1.0), max_entries_per_cycle. "
        "Every recommendation must be justified by the statistics and advisory. "
        "Output JSON keys: policy_patch { min_confluence_delta, block_regimes, "
        "prefer_patterns, avoid_patterns, size_multiplier, max_entries_per_cycle, "
        "confidence (0-1), requires_min_samples, reasons (array), human_summary }. "
        "Output JSON only."
    )

