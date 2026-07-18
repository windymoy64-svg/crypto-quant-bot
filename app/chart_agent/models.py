"""Data models for Chart Reader Agent output."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


# ---------------------------------------------------------------------------
# Candle Pattern models
# ---------------------------------------------------------------------------

PatternDirection = Literal["BULLISH", "BEARISH", "NEUTRAL"]
PatternStrength = Literal["STRONG", "MODERATE", "WEAK"]


@dataclass(frozen=True)
class CandlePatternDetection:
    """A single detected candle pattern."""

    name: str
    direction: PatternDirection
    strength: PatternStrength
    candle_count: int
    start_index: int
    end_index: int
    reliability: float  # 0-100
    description: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Structure models
# ---------------------------------------------------------------------------

StructureBreakType = Literal["BOS", "CHoCH"]
TrendDirection = Literal["UP", "DOWN", "SIDE"]


@dataclass(frozen=True)
class StructureBreak:
    """Break of Structure or Change of Character event."""

    break_type: StructureBreakType
    direction: Literal["BULLISH", "BEARISH"]
    price: float
    index: int
    timestamp: str
    swing_origin_index: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OrderBlock:
    """Order block (last opposing candle before displacement)."""

    direction: Literal["BULLISH", "BEARISH"]
    top: float
    bottom: float
    index: int
    timestamp: str
    mitigated: bool = False
    tested: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def midpoint(self) -> float:
        return (self.top + self.bottom) / 2

    def contains(self, price: float) -> bool:
        return self.bottom <= price <= self.top


@dataclass(frozen=True)
class BreakerBlock:
    """Breaker block (failed order block that becomes opposite zone)."""

    direction: Literal["BULLISH", "BEARISH"]
    top: float
    bottom: float
    index: int
    timestamp: str
    mitigated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Confluence & Analysis models
# ---------------------------------------------------------------------------

BiasDirection = Literal["BULLISH", "BEARISH", "NEUTRAL"]


@dataclass(frozen=True)
class TechniqueSignal:
    """Output from a single technique/strategy analysis."""

    technique: str
    bias: BiasDirection
    confidence: float  # 0-100
    weight: float  # importance in current regime
    reasons: list[str]
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["reasons"] = list(self.reasons)
        return data


@dataclass(frozen=True)
class KeyLevel:
    """Important price level identified by the agent."""

    price: float
    kind: str  # "support", "resistance", "liquidity", "fvg", "order_block"
    strength: PatternStrength
    source: str
    fresh: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ChartReading:
    """Complete chart analysis output from the agent."""

    symbol: str
    timestamp: str

    # Overall bias
    bias: BiasDirection
    bias_confidence: float  # 0-100
    confluence_score: float  # 0-100

    # Market context
    regime: str
    regime_confidence: float

    # Trend structure per timeframe
    htf_trend: TrendDirection
    mtf_trend: TrendDirection
    ltf_trend: TrendDirection
    trends_aligned: bool

    # Detected elements
    candle_patterns: list[CandlePatternDetection]
    structure_breaks: list[StructureBreak]
    order_blocks: list[OrderBlock]
    key_levels: list[KeyLevel]

    # Individual technique signals
    technique_signals: list[TechniqueSignal]

    # Human-readable
    narrative: str
    reasons: list[str]

    # Suggested context (NOT a trade decision)
    suggested_bias: BiasDirection
    entry_zone: tuple[float, float] | None = None
    invalidation_level: float | None = None
    techniques_used: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp,
            "bias": self.bias,
            "bias_confidence": self.bias_confidence,
            "confluence_score": self.confluence_score,
            "regime": self.regime,
            "regime_confidence": self.regime_confidence,
            "htf_trend": self.htf_trend,
            "mtf_trend": self.mtf_trend,
            "ltf_trend": self.ltf_trend,
            "trends_aligned": self.trends_aligned,
            "candle_patterns": [p.to_dict() for p in self.candle_patterns],
            "structure_breaks": [s.to_dict() for s in self.structure_breaks],
            "order_blocks": [o.to_dict() for o in self.order_blocks],
            "key_levels": [k.to_dict() for k in self.key_levels],
            "technique_signals": [t.to_dict() for t in self.technique_signals],
            "narrative": self.narrative,
            "reasons": list(self.reasons),
            "suggested_bias": self.suggested_bias,
            "entry_zone": list(self.entry_zone) if self.entry_zone else None,
            "invalidation_level": self.invalidation_level,
            "techniques_used": list(self.techniques_used),
            "meta": self.meta,
        }
