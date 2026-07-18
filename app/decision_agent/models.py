"""Data models for Decision Maker Agent."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


ActionType = Literal["ENTRY_BUY", "ENTRY_SELL", "HOLD", "EXIT", "SKIP"]
DecisionConfidence = Literal["HIGH", "MEDIUM", "LOW"]


@dataclass(frozen=True)
class EntryPlan:
    """Concrete entry plan with price levels."""

    side: Literal["BUY", "SELL"]
    entry_price: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float | None = None
    take_profit_3: float | None = None
    risk_reward: float = 0.0
    position_size_percent: float = 1.0  # % of balance

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExitPlan:
    """Exit recommendation for an open position."""

    urgency: Literal["IMMEDIATE", "NEXT_CANDLE", "TRAILING"]
    reason: str
    suggested_exit_price: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Decision:
    """Final output from Decision Maker Agent.

    This is what gets sent to the Executor Agent.
    """

    action: ActionType
    symbol: str
    confidence: DecisionConfidence
    confidence_score: float  # 0-100 numeric
    reasons: list[str]

    # Entry details (only when action is ENTRY_BUY or ENTRY_SELL)
    entry_plan: EntryPlan | None = None

    # Exit details (only when action is EXIT)
    exit_plan: ExitPlan | None = None

    # Learning-informed adjustments
    learning_boost: float = 0.0  # +/- adjustment from learning
    learning_reasons: list[str] = field(default_factory=list)

    # Source data references
    regime: str = "MIXED"
    confluence_score: float = 0.0
    timestamp: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "symbol": self.symbol,
            "confidence": self.confidence,
            "confidence_score": self.confidence_score,
            "reasons": list(self.reasons),
            "entry_plan": self.entry_plan.to_dict() if self.entry_plan else None,
            "exit_plan": self.exit_plan.to_dict() if self.exit_plan else None,
            "learning_boost": self.learning_boost,
            "learning_reasons": list(self.learning_reasons),
            "regime": self.regime,
            "confluence_score": self.confluence_score,
            "timestamp": self.timestamp,
            "meta": self.meta,
        }
