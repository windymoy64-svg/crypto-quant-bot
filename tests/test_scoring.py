from app.market.sample_data import load_sample_candles
from app.scoring.engine import ScoreEngine
from app.signals.builder import build_signal


def test_score_engine_is_deterministic() -> None:
    candles = load_sample_candles("BTCUSDT")
    engine = ScoreEngine.from_json("configs/rules.json")

    first = engine.score(candles)
    second = engine.score(candles)

    assert first.total_score == second.total_score
    assert first.confidence == second.confidence
    assert first.action == second.action
    assert first.rules


def test_score_engine_returns_explainable_rule_results() -> None:
    candles = load_sample_candles("BTCUSDT")
    engine = ScoreEngine.from_json("configs/rules.json")

    score = engine.score(candles)
    rule = score.rules[0]

    assert rule.rule_id == "RULE_001"
    assert rule.rule_name == "EMA20 above EMA50"
    assert isinstance(rule.passed, bool)
    assert rule.raw_weight == 4.0
    assert rule.applied_weight == 4.0
    assert rule.score in {0.0, 4.0}
    assert rule.reason


def test_signal_outputs_json_ready_payload() -> None:
    candles = load_sample_candles("BTCUSDT")
    engine = ScoreEngine.from_json("configs/rules.json")
    signal = build_signal("BTCUSDT", candles, engine.score(candles))

    payload = signal.to_dict()

    assert payload["symbol"] == "BTCUSDT"
    assert payload["action"] in {"BUY", "WATCH", "SKIP"}
    assert isinstance(payload["take_profit"], list)
    assert payload["meta"]["passed_rules"]
