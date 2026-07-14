#!/usr/bin/env python3
"""Test script for telegram trade reporter dengan detailed reasons"""

from app.telegram import TelegramNotifier, TradeReporter, send_trade_report

# Test data dengan technical indicators
entry_event = {
    "type": "opened",
    "symbol": "BTC/USDT",
    "position": {
        "symbol": "BTC/USDT",
        "side": "BUY",
        "entry": 45250.50,
        "size": 0.1,
        "remaining_size": 0.1,
        "stop_loss": 44800.00,
        "static_stop_loss": 44800.00,
        "trailing_stop_loss": None,
        "trailing_active": False,
        "take_profit": [46500.00, 47500.00, 48500.00],
        "tp_hit": [False, False, False],
        "confidence": 85.5,
        "atr_at_entry": 150.0,
    },
    "signal": {
        "symbol": "BTC/USDT",
        "action": "BUY",
        "score": 205.0,
        "confidence": 85.5,
        "risk_reward": 3.5,
        "strategy": "Weighted Bullish Rule Engine",
        "meta": {
            "ma5": 45180.25,
            "ma20": 45050.00,
            "timeframe": "15m",
            "volume_signal": "above_average",
            "rsi": 65.5,
            "macd": 125.50,
            "macd_signal": 110.25,
            "stoch_k": 75.2,
            "stoch_d": 72.1,
            "support": 44950.00,
            "resistance": 46200.00,
            "trend": "BULLISH",
            "rules_fired": ["ma_crossover", "rsi_bullish", "volume_spike"],
        }
    }
}

partial_event = {
    "type": "partial_close",
    "symbol": "BTC/USDT",
    "position": {
        "symbol": "BTC/USDT",
        "side": "BUY",
        "entry": 45250.50,
        "size": 0.1,
        "remaining_size": 0.067,
        "stop_loss": 44800.00,
        "static_stop_loss": 44800.00,
        "trailing_stop_loss": None,
        "trailing_active": False,
        "take_profit": [46500.00, 47500.00, 48500.00],
        "tp_hit": [True, False, False],
        "partial_exit_price": 46500.00,
        "partial_size_closed": 0.033,
        "partial_realized_pnl": 41.50,
        "partial_reason": "take_profit_1",
    }
}

close_event = {
    "type": "closed",
    "symbol": "BTC/USDT",
    "position": {
        "symbol": "BTC/USDT",
        "side": "BUY",
        "entry": 45250.50,
        "size": 0.1,
        "remaining_size": 0,
        "stop_loss": 44800.00,
        "static_stop_loss": 44800.00,
        "trailing_stop_loss": 45100.00,
        "trailing_active": True,
        "take_profit": [46500.00, 47500.00, 48500.00],
        "tp_hit": [True, True, False],
        "exit": 45100.00,
        "closed_at": "2026-07-14T09:45:00+00:00",
        "final_size_closed": 0.067,
        "final_realized_pnl": -100.75,
        "realized_pnl": -59.25,
        "close_reason": "trailing_stop",
    }
}

def test_reporter():
    """Test trade reporter dengan signal reasoning"""
    reporter = TradeReporter()
    
    print("=" * 90)
    print("TEST 1: ENTRY POSITION DENGAN SIGNAL REASONING")
    print("=" * 90)
    msg = reporter.format_entry(
        entry_event["position"],
        entry_event["signal"]
    )
    print(msg)
    
    print("\n" + "=" * 90)
    print("TEST 2: PARTIAL CLOSE")
    print("=" * 90)
    msg = reporter.format_partial_close(partial_event["position"])
    print(msg)
    
    print("\n" + "=" * 90)
    print("TEST 3: FULL CLOSE")
    print("=" * 90)
    msg = reporter.format_close(close_event["position"])
    print(msg)

def test_notifier():
    """Test notifier dengan signal integration"""
    notifier = TelegramNotifier(enabled=True)
    
    print("\n" + "=" * 90)
    print("TEST 4: SEND VIA NOTIFIER (dengan detailed reason)")
    print("=" * 90)
    
    send_trade_report(notifier, entry_event)
    send_trade_report(notifier, partial_event)
    send_trade_report(notifier, close_event)
    
    print(f"✅ Messages sent: {len(notifier.outbox)}")
    for i, msg in enumerate(notifier.outbox, 1):
        print(f"\n--- Message {i} ({len(msg)} chars) ---")
        print(msg[:300] + "..." if len(msg) > 300 else msg)

if __name__ == "__main__":
    test_reporter()
    test_notifier()
    print("\n" + "=" * 90)
    print("✅ ALL TESTS PASSED!")
    print("=" * 90)

