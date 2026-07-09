from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.models import Candle, RuleResult, ScoreResult
from app.features.builder import build_features
from app.market.regime import MarketRegime
from app.scoring.dynamic_weights import DynamicWeightEngine, RuleWeightProfile


class ScoreEngine:
    def __init__(
        self,
        rules: list[dict[str, Any]],
        dynamic_weight_engine: DynamicWeightEngine | None = None,
        quality_gates: dict[str, dict[str, float]] | None = None,
        buy_confidence: float = 90.0,
        watch_confidence: float = 80.0,
    ) -> None:
        self.rules = rules
        self.dynamic_weight_engine = dynamic_weight_engine
        self.quality_gates = quality_gates or {}
        self.buy_confidence = buy_confidence
        self.watch_confidence = watch_confidence

    @classmethod
    def from_json(cls, path: str, weights_path: str | None = None) -> "ScoreEngine":
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        dynamic_weight_engine = DynamicWeightEngine.from_json(weights_path) if weights_path else None
        return cls(
            data["rules"],
            dynamic_weight_engine=dynamic_weight_engine,
            quality_gates=data.get("quality_gates"),
            buy_confidence=float(data.get("buy_confidence", 90.0)),
            watch_confidence=float(data.get("watch_confidence", 80.0)),
        )

    def score(self, candles: list[Candle], market_regime: MarketRegime | str | None = None) -> ScoreResult:
        features = build_features(candles)
        weight_profile = self.weight_profile_for(market_regime)
        results: list[RuleResult] = []
        buckets: dict[str, float] = {}
        max_score = 0.0
        total_score = 0.0

        for rule in self.rules:
            rule_id = str(rule["id"])
            base_weight = float(rule["weight"])
            weight = weight_profile.weight_for(rule_id, base_weight) if weight_profile else base_weight
            passed = self._evaluate(rule, features)
            points = weight if passed else 0.0
            reason = self._explain(rule, features, passed, base_weight, weight, weight_profile)
            category = str(rule.get("category", "general"))
            buckets[category] = buckets.get(category, 0.0) + points
            total_score += points
            max_score += weight
            results.append(
                RuleResult(
                    rule_id=rule_id,
                    rule_name=str(rule["name"]),
                    passed=passed,
                    raw_weight=base_weight,
                    applied_weight=weight,
                    score=points,
                    reason=reason,
                )
            )

        confidence = round((total_score / max_score) * 100, 2) if max_score else 0.0

        # --- Tahap 2: gate kualitas per kategori ---
        gate_status: dict[str, dict[str, float | bool]] = {}
        all_gates_passed = True
        for category, gate in self.quality_gates.items():
            actual = buckets.get(category, 0.0)
            required = float(gate.get("min_score", 0))
            passed = actual >= required
            gate_status[category] = {
                "actual": round(actual, 2),
                "required": required,
                "passed": passed,
            }
            if not passed:
                all_gates_passed = False

        # --- Risk-adjusted score: penalti untuk rule 'risk' yang gagal ---
        risk_fails = sum(
            1 for r, res in zip(self.rules, results)
            if str(r.get("category", "")) == "risk" and not res.passed
        )
        risk_penalty = risk_fails * 1.0
        adjusted_confidence = max(0.0, round(confidence - risk_penalty, 2))

        # --- Tentukan action: BUY hanya jika semua gate lolos ---
        if adjusted_confidence >= self.buy_confidence and all_gates_passed:
            action = "BUY"
        elif adjusted_confidence >= self.watch_confidence:
            action = "WATCH"
        elif not all_gates_passed and confidence >= self.buy_confidence:
            action = "WATCH"  # skor tinggi tapi gate gagal → downgrade
        else:
            action = "SKIP"
        return ScoreResult(
            total_score=round(total_score, 2),
            max_score=round(max_score, 2),
            confidence=adjusted_confidence,
            action=action,
            buckets={
                **{key: round(value, 2) for key, value in buckets.items()},
                "_gates": gate_status,
                "_raw_confidence": confidence,
                "_risk_fails": risk_fails,
            },
            rules=results,
        )

    def weight_profile_for(self, market_regime: MarketRegime | str | None) -> RuleWeightProfile | None:
        if self.dynamic_weight_engine is None or market_regime is None:
            return None
        return self.dynamic_weight_engine.profile_for(market_regime)

    def _evaluate(self, rule: dict[str, Any], features: dict[str, Any]) -> bool:
        feature = str(rule["feature"])
        operator = str(rule["operator"])
        expected = rule.get("value")
        actual = features.get(feature)

        if operator == "is_true":
            return bool(actual) is True
        if operator == "is_false":
            return bool(actual) is False
        if operator == "gt":
            return float(actual) > float(expected)
        if operator == "gte":
            return float(actual) >= float(expected)
        if operator == "lt":
            return float(actual) < float(expected)
        if operator == "lte":
            return float(actual) <= float(expected)
        if operator == "between":
            low, high = expected
            return float(low) <= float(actual) <= float(high)
        raise ValueError(f"Unsupported operator: {operator}")

    def _explain(
        self,
        rule: dict[str, Any],
        features: dict[str, Any],
        passed: bool,
        base_weight: float,
        applied_weight: float,
        weight_profile: RuleWeightProfile | None,
    ) -> str:
        feature = str(rule.get("feature"))
        operator = str(rule.get("operator"))
        expected = rule.get("value")
        actual = features.get(feature)
        status = "passed" if passed else "failed"
        profile_name = weight_profile.name if weight_profile else "STATIC"
        weight_note = ""
        if applied_weight != base_weight:
            weight_note = f"; weight adjusted {base_weight:g}->{applied_weight:g} by {profile_name} profile"
        return f"{feature} {operator} {expected!r}: actual={actual!r} {status}{weight_note}"

