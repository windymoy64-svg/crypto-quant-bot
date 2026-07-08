from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class RiskRewardCheck:
    valid: bool
    reason: str
    ratio: float
    minimum: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class RiskRewardValidator:
    def __init__(self, minimum_ratio: float = 1.2) -> None:
        self.minimum_ratio = minimum_ratio

    def validate_long(self, entry: float, stop_loss: float, take_profit: float) -> RiskRewardCheck:
        risk = entry - stop_loss
        reward = take_profit - entry
        if entry <= 0 or risk <= 0 or reward <= 0:
            return RiskRewardCheck(False, "invalid_risk_reward", 0.0, self.minimum_ratio)
        ratio = reward / risk
        valid = ratio >= self.minimum_ratio
        reason = "ok" if valid else "risk_reward_too_low"
        return RiskRewardCheck(valid, reason, round(ratio, 4), self.minimum_ratio)