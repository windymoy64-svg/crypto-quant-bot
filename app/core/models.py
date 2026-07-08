from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class Candle:
    symbol: str
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class RuleResult:
    rule_id: str
    rule_name: str
    passed: bool
    raw_weight: float
    applied_weight: float
    score: float
    reason: str

    @property
    def name(self) -> str:
        return self.rule_name

    @property
    def weight(self) -> float:
        return self.applied_weight

    @property
    def points(self) -> float:
        return self.score

    @property
    def details(self) -> dict[str, Any]:
        return {
            "base_weight": self.raw_weight,
            "applied_weight": self.applied_weight,
            "weight_profile": self._weight_profile_from_reason(),
            "reason": self.reason,
        }

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def _weight_profile_from_reason(self) -> str:
        marker = " by "
        suffix = " profile"
        if marker in self.reason and self.reason.endswith(suffix):
            return self.reason.rsplit(marker, 1)[1][: -len(suffix)]
        return "STATIC"


@dataclass(frozen=True)
class FeatureContribution:
    feature: str
    score: float
    percentage: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ScoreResult:
    total_score: float
    max_score: float
    confidence: float
    action: Literal["BUY", "WATCH", "SKIP"]
    buckets: dict[str, float]
    rules: list[RuleResult]


@dataclass(frozen=True)
class TradingSignal:
    symbol: str
    action: Literal["BUY", "WATCH", "SKIP", "SELL"]
    score: float
    confidence: float
    entry: float
    stop_loss: float
    take_profit: list[float]
    risk_reward: float
    risk: Literal["LOW", "MEDIUM", "HIGH"]
    strategy: str
    meta: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
