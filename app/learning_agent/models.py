"""Data models for Learning Agent."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


# ---------------------------------------------------------------------------
# Trade Record — enriched journal entry with chart context
# ---------------------------------------------------------------------------

TradeOutcome = Literal["TP", "SL", "TRAILING", "BREAKEVEN", "MANUAL", "INVALIDATION"]
HoldDecision = Literal["HOLD", "CAUTION", "EXIT"]


@dataclass(frozen=True)
class ChartObservation:
    """Immutable raw reading sent from Chart Agent to Learning Agent.

    Observations are stored even before there is an entry. This preserves the
    market context that later explains why a decision, hold, TP, or SL happened.
    """

    observation_id: str
    symbol: str
    timestamp: str
    stage: Literal["ENTRY_CANDIDATE", "POSITION_MONITOR", "EXIT"]
    scanner_confidence: float
    scanner_gates_passed: bool
    chart_reading: dict[str, Any]
    decision: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TradeRecord:
    """A completed trade with full context for learning.

    This extends the existing TradeJournalEntry with chart reading context
    so the Learning Agent knows WHY a trade was taken and what happened.
    """

    # Identity
    trade_id: str
    symbol: str
    side: Literal["BUY", "SELL"]
    timestamp_entry: str
    timestamp_exit: str

    # Prices
    entry_price: float
    exit_price: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float | None = None
    take_profit_3: float | None = None

    # Result
    outcome: TradeOutcome = "MANUAL"
    pnl_percent: float = 0.0
    pnl_absolute: float = 0.0
    hold_duration_minutes: float = 0.0
    max_favorable_excursion: float = 0.0  # best unrealized PnL%
    max_adverse_excursion: float = 0.0  # worst unrealized PnL%

    # Context at entry (from Chart Reader Agent)
    regime_at_entry: str = "MIXED"
    bias_at_entry: str = "NEUTRAL"
    confluence_at_entry: float = 0.0
    htf_trend_at_entry: str = "SIDE"
    patterns_at_entry: list[str] = field(default_factory=list)
    techniques_at_entry: list[str] = field(default_factory=list)
    key_levels_at_entry: list[float] = field(default_factory=list)

    # Context at exit
    regime_at_exit: str = "MIXED"
    bias_at_exit: str = "NEUTRAL"
    exit_reason_detail: str = ""

    # Strategy/technique that triggered entry
    entry_strategy: str = ""
    entry_confidence: float = 0.0

    # Raw meta
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def is_win(self) -> bool:
        return self.pnl_percent > 0

    @property
    def risk_reward_achieved(self) -> float:
        """Actual RR achieved (positive = favorable)."""
        risk = abs(self.entry_price - self.stop_loss)
        if risk <= 0:
            return 0.0
        reward = abs(self.exit_price - self.entry_price)
        return reward / risk if self.is_win else -(reward / risk)


# ---------------------------------------------------------------------------
# Learning Insight — output from Learning Agent to Decision Maker
# ---------------------------------------------------------------------------


@dataclass
class PatternInsight:
    """Statistical insight about a specific pattern/technique combo."""

    pattern_name: str
    regime: str
    total_trades: int
    win_count: int
    loss_count: int
    winrate: float  # 0-100
    avg_pnl_percent: float
    avg_rr_achieved: float
    avg_hold_minutes: float
    best_pnl: float
    worst_pnl: float
    last_seen: str  # timestamp

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def is_reliable(self) -> bool:
        """At least 5 trades to be statistically meaningful."""
        return self.total_trades >= 5


@dataclass
class RegimeInsight:
    """How well the system performs in a specific regime."""

    regime: str
    total_trades: int
    winrate: float
    avg_pnl_percent: float
    avg_confluence_at_entry: float
    best_techniques: list[str]  # ranked by winrate in this regime
    worst_techniques: list[str]
    avg_hold_minutes: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SymbolInsight:
    """Performance insight per trading pair."""

    symbol: str
    total_trades: int
    winrate: float
    avg_pnl_percent: float
    avg_hold_minutes: float
    preferred_side: str  # "BUY" or "SELL" based on history
    best_regime: str
    worst_regime: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LearningInsight:
    """Complete wisdom package sent to Decision Maker.

    Contains statistical summaries and pattern-specific insights that
    help the Decision Maker calibrate its confidence and decisions.
    """

    # Overall stats
    total_trades: int
    overall_winrate: float
    overall_avg_pnl: float
    overall_profit_factor: float  # gross wins / gross losses

    # Breakdown insights
    pattern_insights: list[PatternInsight]
    regime_insights: list[RegimeInsight]
    symbol_insights: list[SymbolInsight]

    # Top-level recommendations
    hot_patterns: list[str]  # patterns with winrate > 65% and >= 5 trades
    cold_patterns: list[str]  # patterns with winrate < 40%
    best_regime: str  # regime with highest winrate
    worst_regime: str  # regime with lowest winrate

    # Confidence calibration
    avg_confluence_winners: float  # avg confluence score of winning trades
    avg_confluence_losers: float  # avg confluence score of losing trades
    min_confluence_recommended: float  # suggested minimum confluence

    # Timing
    last_updated: str
    data_since: str  # earliest trade in dataset

    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_trades": self.total_trades,
            "overall_winrate": self.overall_winrate,
            "overall_avg_pnl": self.overall_avg_pnl,
            "overall_profit_factor": self.overall_profit_factor,
            "pattern_insights": [p.to_dict() for p in self.pattern_insights],
            "regime_insights": [r.to_dict() for r in self.regime_insights],
            "symbol_insights": [s.to_dict() for s in self.symbol_insights],
            "hot_patterns": self.hot_patterns,
            "cold_patterns": self.cold_patterns,
            "best_regime": self.best_regime,
            "worst_regime": self.worst_regime,
            "avg_confluence_winners": self.avg_confluence_winners,
            "avg_confluence_losers": self.avg_confluence_losers,
            "min_confluence_recommended": self.min_confluence_recommended,
            "last_updated": self.last_updated,
            "data_since": self.data_since,
            "meta": self.meta,
        }

