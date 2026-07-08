from __future__ import annotations

from app.live import LiveConfig, LiveOrder, OpenOrderSummary, OrderHistory, OrderIntentEngine, SymbolCooldown


def _order(symbol: str = "BTC/USDT") -> LiveOrder:
    return LiveOrder(
        symbol=symbol,
        side="BUY",
        order_type="MARKET",
        quantity=0.001,
        quote_amount=100.0,
        price=100000.0,
        stop_loss=99000.0,
        take_profit=101500.0,
        timestamp="2026-07-07T00:00:00+00:00",
    )


def _open_order(symbol: str = "BTCUSDT") -> OpenOrderSummary:
    return OpenOrderSummary(
        symbol=symbol,
        side="BUY",
        type="MARKET",
        status="NEW",
        orig_qty=0.001,
        executed_qty=0.0,
        price=100000.0,
    )


def test_order_intent_rejects_duplicate_order() -> None:
    history = OrderHistory()
    history.add("BTC/USDT", "BUY", "OPEN", "2026-07-07T00:00:00+00:00")

    result = OrderIntentEngine(LiveConfig(), history=history).evaluate(_order(), now=1000.0)

    assert result.approved is False
    assert result.duplicate is True
    assert result.reason == "intent_duplicate_order"


def test_order_intent_rejects_cooldown() -> None:
    cooldown = SymbolCooldown(cooldown_seconds=300)
    cooldown.mark("BTC/USDT", now=1000.0)

    result = OrderIntentEngine(LiveConfig(cooldown_seconds=300), cooldown=cooldown).evaluate(_order(), now=1100.0)

    assert result.approved is False
    assert result.cooldown is True
    assert result.reason == "intent_symbol_cooldown"


def test_order_intent_rejects_existing_position() -> None:
    result = OrderIntentEngine(LiveConfig(), position_symbols={"BTCUSDT"}).evaluate(_order(), now=1000.0)

    assert result.approved is False
    assert result.position_exists is True
    assert result.reason == "intent_position_exists"


def test_order_intent_rejects_existing_open_order() -> None:
    result = OrderIntentEngine(LiveConfig()).evaluate(_order(), open_orders=[_open_order()], now=1000.0)

    assert result.approved is False
    assert result.same_side_open is True
    assert result.reason == "intent_same_side_open_order"


def test_order_intent_allows_new_order() -> None:
    result = OrderIntentEngine(LiveConfig()).evaluate(_order(), now=1000.0)

    assert result.approved is True
    assert result.reason == "intent_approved"