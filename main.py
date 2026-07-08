from __future__ import annotations

import json

from app.backtest.runner import run_demo_backtest
from app.market.sample_data import load_sample_candles
from app.scoring.engine import ScoreEngine
from app.signals.builder import build_signal


def main() -> None:
    candles = load_sample_candles("BTCUSDT")
    engine = ScoreEngine.from_json("configs/rules.json")
    score = engine.score(candles)
    signal = build_signal(symbol="BTCUSDT", candles=candles, score=score)
    backtest = run_demo_backtest(candles, signal)

    print("Signal JSON:")
    print(json.dumps(signal.to_dict(), indent=2))
    print("\nPaper result:")
    print(json.dumps(backtest, indent=2))


if __name__ == "__main__":
    main()
