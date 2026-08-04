#!/usr/bin/env python3
"""Simple Telegram test."""
import sys
sys.path.insert(0, '/opt/crypto-quant-bot')

from app.settings.telegram_preferences import load_telegram_preferences

print("="*70)
print("📱 TELEGRAM SETTINGS STATUS")
print("="*70)

prefs = load_telegram_preferences()

print(f"\n✅ Saved in database:")
print(f"   Enabled: {prefs.enabled}")
print(f"   Token: {prefs.bot_token_masked or '(not set)'}")  
print(f"   Chat ID: {prefs.chat_id_masked or '(not set)'}")

if prefs.enabled and prefs.bot_token_masked and prefs.chat_id_masked:
    print("\n" + "="*70)
    print("✅ CONFIGURED - Settings saved successfully!")
    print("="*70)
    print("\nTo ACTIVATE notifications:")
    print("1. Set environment variables:")
    print('   export TELEGRAM_BOT_TOKEN="your_bot_token_from_BotFather"')
    print('   export TELEGRAM_CHAT_ID="your_chat_id_number"')
    print("2. Then test:")
    print('   cd /opt/crypto-quant-bot && python test_send_message.py')
    print("\nOR permanently:")
    print("   Edit systemd service to include these env vars.")
else:
    print("\n❌ NOT CONFIGURED")
    print("Please enter credentials in Dashboard → Settings → Telegram")

print("="*70)
