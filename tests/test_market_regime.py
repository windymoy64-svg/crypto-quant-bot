from app.market.regime import MarketRegimeEngine


def test_regime_engine_detects_trending_bullish() -> None:
    regime = MarketRegimeEngine().analyze(
        {
            "ema20_gt_ema50": True,
            "ema50_gt_ema200": True,
            "price_gt_ema20": True,
            "macd_bullish": True,
            "rsi": 61.0,
            "atr_percent": 1.2,
            "volume_ratio": 1.1,
        }
    )

    assert regime.regime == "TRENDING_BULLISH"
    assert regime.trend_strength == "STRONG"
    assert regime.volatility_state == "NORMAL"
    assert regime.volume_state == "NORMAL"


def test_regime_engine_detects_high_volatility_first() -> None:
    regime = MarketRegimeEngine().analyze(
        {
            "ema20_gt_ema50": True,
            "ema50_gt_ema200": True,
            "price_gt_ema20": True,
            "macd_bullish": True,
            "rsi": 68.0,
            "atr_percent": 3.5,
            "volume_ratio": 1.4,
        }
    )

    assert regime.regime == "HIGH_VOLATILITY"
    assert regime.volatility_state == "HIGH"
    assert regime.volume_state == "HIGH"
    assert regime.confidence > 0


def test_regime_engine_detects_ranging() -> None:
    regime = MarketRegimeEngine().analyze(
        {
            "ema20_gt_ema50": True,
            "ema50_gt_ema200": False,
            "price_gt_ema20": True,
            "macd_bullish": False,
            "rsi": 50.0,
            "atr_percent": 1.0,
            "volume_ratio": 1.0,
        }
    )

    assert regime.regime == "RANGING"
    assert regime.trend_strength == "WEAK"