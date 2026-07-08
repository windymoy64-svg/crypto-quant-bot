from app.market.regime import MarketRegime
from app.market.sample_data import load_sample_candles
from app.market.multi_timeframe import MultiTimeframeScanner
from app.scoring.dynamic_weights import DynamicWeightEngine
from app.scoring.engine import ScoreEngine


def test_dynamic_weight_engine_returns_regime_profile() -> None:
    engine = DynamicWeightEngine.from_json("configs/rule_weights.json")
    regime = MarketRegime(
        regime="TRENDING_BULLISH",
        trend_strength="STRONG",
        volatility_state="NORMAL",
        volume_state="NORMAL",
        confidence=95.0,
    )

    profile = engine.profile_for(regime)

    assert profile.name == "TRENDING_BULLISH"
    assert profile.weights["RULE_001"] == 5.0
    assert profile.weight_for("RULE_UNKNOWN", 7.0) == 7.0


def test_dynamic_weight_engine_falls_back_to_mixed_profile() -> None:
    engine = DynamicWeightEngine.from_json("configs/rule_weights.json")

    profile = engine.profile_for("UNKNOWN_REGIME")

    assert profile.name == "MIXED"
    assert "RULE_001" in profile.weights


def test_score_engine_uses_dynamic_weights_when_regime_is_provided() -> None:
    candles = load_sample_candles("BTCUSDT")
    static_score = ScoreEngine.from_json("configs/rules.json").score(candles)
    dynamic_score = ScoreEngine.from_json(
        "configs/rules.json",
        weights_path="configs/rule_weights.json",
    ).score(candles, market_regime="HIGH_VOLATILITY")

    dynamic_rule = next(rule for rule in dynamic_score.rules if rule.rule_id == "RULE_001")

    assert dynamic_score.max_score != static_score.max_score
    assert dynamic_rule.applied_weight == 3.0
    assert dynamic_rule.raw_weight == 4.0
    assert dynamic_rule.weight == 3.0
    assert dynamic_rule.details["base_weight"] == 4.0
    assert dynamic_rule.details["weight_profile"] == "HIGH_VOLATILITY"
    assert "HIGH_VOLATILITY" in dynamic_rule.reason


def test_multi_timeframe_result_exports_rules_to_json() -> None:
    scanner = MultiTimeframeScanner(fallback_to_sample_data=True)

    result = scanner.scan_symbol("BTCUSDT", timeframes=["1h"], limit=100)
    payload = result.to_dict()

    assert payload["rules"]
    assert payload["rules"][0]["rule_id"] == "RULE_001"
    assert "reason" in payload["rules"][0]
    assert payload["signals"][0]["rules"]