from app.research.vibe_trading_bridge import VibeTradingBridge


def test_vibe_trading_bridge_availability_returns_bool() -> None:
    bridge = VibeTradingBridge()

    assert isinstance(bridge.is_available(), bool)


def test_vibe_trading_bridge_rejects_empty_prompt() -> None:
    bridge = VibeTradingBridge(executable="definitely-not-installed")

    try:
        bridge.run_research("   ")
    except ValueError as exc:
        assert "prompt" in str(exc)
    else:
        raise AssertionError("Expected empty prompt to fail")
