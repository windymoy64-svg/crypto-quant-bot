from app.execution.live_executor import LiveExecutor, LiveTradingSettings


def test_live_executor_blocks_by_default() -> None:
    settings = LiveTradingSettings(
        enabled=False,
        dry_run=True,
        exchange="binance",
        quote_asset="USDT",
        max_order_notional=25,
        allowed_symbols=["BTC/USDT"],
        min_confidence=95,
        allow_market_orders=True,
    )
    decision = LiveExecutor(settings).evaluate_signal(
        {
            "symbol": "BTC/USDT",
            "action": "BUY",
            "confidence": 99,
            "entry": 100,
        }
    )

    assert decision["status"] == "blocked"
    assert decision["reason"] == "live_trading_disabled"


def test_live_executor_dry_run_before_order() -> None:
    settings = LiveTradingSettings(
        enabled=True,
        dry_run=True,
        exchange="binance",
        quote_asset="USDT",
        max_order_notional=25,
        allowed_symbols=["BTC/USDT"],
        min_confidence=95,
        allow_market_orders=True,
    )
    decision = LiveExecutor(settings).evaluate_signal(
        {
            "symbol": "BTC/USDT",
            "action": "BUY",
            "confidence": 99,
            "entry": 100,
        }
    )

    assert decision["status"] == "dry_run"
    assert decision["reason"] == "dry_run_enabled"
