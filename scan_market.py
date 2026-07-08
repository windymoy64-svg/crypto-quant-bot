from __future__ import annotations

import json

from app.market.multi_timeframe import MultiTimeframeResult, MultiTimeframeScanner


DEFAULT_SYMBOLS = [
    "BTC/USDT",
    "ETH/USDT",
    "SOL/USDT",
    "BNB/USDT",
    "XRP/USDT",
    "DOGE/USDT",
    "ADA/USDT",
    "LINK/USDT",
    "AVAX/USDT",
    "SUI/USDT",
]

TIMEFRAMES = ["5m", "15m", "1h", "4h", "1d"]


def print_multi_timeframe_results(results: list[MultiTimeframeResult]) -> None:
    for result in results:
        print("=" * 16)
        print(result.symbol)
        print("=" * 16)
        print("MARKET REGIME")
        print("=" * 16)
        print(f"Regime         : {result.market_regime.regime}")
        print(f"Trend Strength : {result.market_regime.trend_strength}")
        print(f"Volatility     : {result.market_regime.volatility_state}")
        print(f"Volume         : {result.market_regime.volume_state}")
        print(f"Confidence     : {result.market_regime.confidence}")
        print("=" * 16)
        print("WEIGHT PROFILE")
        print("=" * 16)
        if result.weight_profile:
            print(f"Profile        : {result.weight_profile.name}")
            print(f"Rule Count     : {len(result.weight_profile.weights)}")
            print(f"Total Weight   : {result.weight_profile.total_weight}")
        else:
            print("Profile        : STATIC")
        print("=" * 16)
        print("SCORE")
        print("=" * 16)
        print(f"{'Timeframe':<10} {'Score':>7} {'Confidence':>11} {'Action':<8}")
        for signal in result.signals:
            print(f"{signal.timeframe:<10} {signal.score:>7.2f} {signal.confidence:>11.2f} {signal.action:<8}")
        print("=" * 16)
        print("RULE EXPLANATION")
        print("=" * 16)
        print(f"{'Rule':<34} {'Status':<6} {'Weight':>8} {'Score':>8} Reason")
        for rule in result.rules:
            status = "PASS" if rule.passed else "FAIL"
            rule_label = f"{rule.rule_id} {rule.rule_name}"[:34]
            print(
                f"{rule_label:<34} {status:<6} {rule.applied_weight:>8.2f} "
                f"{rule.score:>8.2f} {rule.reason}"
            )
        print("=" * 16)
        print("FEATURE IMPORTANCE")
        print("=" * 16)
        print(f"{'Feature':<20} {'Contribution':>12} {'Percentage':>11}")
        for contribution in result.feature_importance:
            print(f"{contribution.feature:<20} {contribution.score:>12.2f} {contribution.percentage:>10.2f}%")
        print("=" * 16)
        print("TOTAL SCORE")
        print("=" * 16)
        print(f"Final Score     : {result.final_score}")
        print(f"Final Confidence: {result.final_confidence}")
        print(f"Trend Alignment : {result.trend_alignment}")
        print(f"Overall Action  : {result.overall_action}")
        print()


def build_json_output(results: list[MultiTimeframeResult]) -> dict[str, object]:
    return {"results": [result.to_dict() for result in results]}


def main() -> None:
    scanner = MultiTimeframeScanner(
        exchange="binance",
        fallback_to_sample_data=True,
    )
    results = scanner.scan_symbols(DEFAULT_SYMBOLS, timeframes=TIMEFRAMES, limit=100)

    print_multi_timeframe_results(results)
    print("\nJSON:")
    print(json.dumps(build_json_output(results), indent=2))


if __name__ == "__main__":
    main()
