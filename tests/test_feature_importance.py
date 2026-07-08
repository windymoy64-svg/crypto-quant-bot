from app.core.models import RuleResult
from app.market.multi_timeframe import MultiTimeframeScanner
from app.scoring.feature_importance import FeatureImportanceEngine


def test_feature_importance_groups_rule_scores() -> None:
    rules = [
        RuleResult("RULE_001", "EMA20 above EMA50", True, 4.0, 5.0, 5.0, "ema20_gt_ema50 passed"),
        RuleResult("RULE_020", "RSI above 50", True, 3.0, 3.0, 3.0, "rsi gte 50 passed"),
        RuleResult("RULE_099", "Unknown condition", False, 2.0, 2.0, 0.0, "unknown failed"),
    ]

    contributions = FeatureImportanceEngine().calculate(rules)
    by_feature = {contribution.feature: contribution for contribution in contributions}

    assert by_feature["EMA"].score == 5.0
    assert by_feature["EMA"].percentage == 62.5
    assert by_feature["RSI"].score == 3.0
    assert by_feature["RSI"].percentage == 37.5
    assert "Other" not in by_feature


def test_multi_timeframe_result_exports_feature_importance_to_json() -> None:
    scanner = MultiTimeframeScanner(fallback_to_sample_data=True)

    result = scanner.scan_symbol("BTCUSDT", timeframes=["1h"], limit=100)
    payload = result.to_dict()

    assert payload["feature_importance"]
    assert {"feature", "score", "percentage"} <= set(payload["feature_importance"][0])