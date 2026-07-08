from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from app.market.regime import MarketRegime


@dataclass(frozen=True)
class RuleWeightProfile:
    name: str
    weights: dict[str, float]

    @property
    def total_weight(self) -> float:
        return round(sum(self.weights.values()), 2)

    def weight_for(self, rule_id: str, default_weight: float) -> float:
        return float(self.weights.get(rule_id, default_weight))

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["total_weight"] = self.total_weight
        return payload


class DynamicWeightEngine:
    def __init__(self, profiles: dict[str, dict[str, float]]) -> None:
        self.profiles = {
            str(profile): {str(rule_id): float(weight) for rule_id, weight in weights.items()}
            for profile, weights in profiles.items()
        }

    @classmethod
    def from_json(cls, path: str) -> "DynamicWeightEngine":
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        return cls(data)

    def profile_for(self, market_regime: MarketRegime | str) -> RuleWeightProfile:
        regime_name = market_regime.regime if isinstance(market_regime, MarketRegime) else str(market_regime)
        profile_name = regime_name if regime_name in self.profiles else "MIXED"
        return RuleWeightProfile(name=profile_name, weights=dict(self.profiles.get(profile_name, {})))

    def get_weights(self, market_regime: MarketRegime | str) -> dict[str, float]:
        return self.profile_for(market_regime).weights

    def weight_for_rule(self, market_regime: MarketRegime | str, rule_id: str, default_weight: float) -> float:
        return self.profile_for(market_regime).weight_for(rule_id, default_weight)