#!/usr/bin/env python3
"""
Demo: Simulate paper trading with telegram reports
Shows how trade reports are sent on position events
"""

import json
from pathlib import Path
from app.paper.realtime_engine import PaperTradingConfig, RealtimePaperTradingEngine
from app.telegram import TelegramNotifier

# Create temporary state for demo
demo_state_path = "/tmp/demo_paper_state.json"
demo_trades_path = "/tmp/demo_paper_trades.jsonl"

# Clean up previous demo files
Path(demo_state_path).unlink(missing_ok=True)
Path(demo_trades_path).unlink(missing_ok=True)

# Configure paper trading
config = PaperTradingConfig(
    enabled=True,
    starting_balance=10000.0,
    risk_percent=2.0,
    max_open_positions=3,
    state_path=demo_state_path,
    trades_path=demo_trades_path,
    max_position_size_percent=15.0,
)

# Initialize telegram notifier
notifier = TelegramNotifier(enabled=True)

# Create engine with telegram integration
engine = RealtimePaperTradingEngine(config, notifier)

# Simulate BUY signal
signal_entry = {
    "symbol": "ETH/USDT",
    "action": "BUY",
    "confidence": 82.5,
    "score": 195.0,
    "entry": 3500.00,
    "stop_loss": 3450.00,
    "take_profit": [3550.00, 3600.00, 3650.00],
    "risk_reward": 2.5,
    "risk": "MEDIUM",
    "strategy": "Demo Strategy",
    "meta": {},
}

print("=" * 80)
print("DEMO 1: Opening Position")
print("=" * 80)
result = engine.process_signals([signal_entry])
print(f"Balance: ${result['balance']:.2f}")
print(f"Open positions: {len(result['open_positions'])}")
print(f"Events: {len(result['events'])}")

if notifier.outbox:
    print("\n📱 Telegram Message:")
    print(notifier.outbox[-1])

# Simulate price hitting TP1
signal_tp1 = {
    **signal_entry,
    "action": "SKIP",
    "entry": 3550.00,  # Price now at TP1
}

print("\n" + "=" * 80)
print("DEMO 2: Price hits TP1 (Partial Close)")
print("=" * 80)
result = engine.process_signals([signal_tp1])
print(f"Balance: ${result['balance']:.2f}")
print(f"Open positions: {len(result['open_positions'])}")
print(f"Events: {len(result['events'])}")

if len(notifier.outbox) > 1:
    print("\n📱 Telegram Message:")
    print(notifier.outbox[-1])

# Simulate price hitting trailing stop
signal_trailing = {
    **signal_entry,
    "action": "SKIP",
    "entry": 3520.00,  # Price drops, trailing stop triggered
}

print("\n" + "=" * 80)
print("DEMO 3: Trailing Stop Hit (Full Close)")
print("=" * 80)
result = engine.process_signals([signal_trailing])
print(f"Balance: ${result['balance']:.2f}")
print(f"Open positions: {len(result['open_positions'])}")
print(f"Events: {len(result['events'])}")

if len(notifier.outbox) > 2:
    print("\n📱 Telegram Message:")
    print(notifier.outbox[-1])

print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)
print(f"Total messages sent: {len(notifier.outbox)}")
print(f"Final balance: ${result['balance']:.2f}")
print(f"Trades logged: {demo_trades_path}")
print("\n✅ Demo completed! Check telegram messages above.")

# Show all messages
print("\n" + "=" * 80)
print("ALL TELEGRAM MESSAGES")
print("=" * 80)
for i, msg in enumerate(notifier.outbox, 1):
    print(f"\n--- Message {i} ---")
    print(msg)
