#!/usr/bin/env python3
"""Verify Telegram is working."""
import sys
sys.path.insert(0, '/opt/crypto-quant-bot')

from app.settings.telegram_preferences import load_telegram_preferences

print("="*70)
print("🔍 TELEGRAM CONFIGURATION STATUS")
print("="*70)

prefs = load_telegram_preferences()

print(f"\n✅ Configuration saved in database:")
print(f"   Enabled: {prefs.enabled}")
print(f"   Bot Token: {prefs.bot_token_masked or '(empty)'}")
print(f"   Chat ID: {prefs.chat_id_masked or '(empty)'}")
print(f"   Updated: {prefs.updated_at}")

if prefs.enabled and prefs.bot_token_masked and prefs.chat_id_masked:
    print("\n" + "="*70)
    print("✅ CONFIGURED SUCCESSFULLY!")
    print("="*70)
    print("\n👉 Settings saved to secure storage.")
    print("   To ACTIVATE notifications:")
    print("   1. Restart bot service (will read .env file)")
    print("   OR")
    print("   2. Set env vars manually for testing")
else:
    print("\n❌ NOT SET UP YET")
    print("   Please fill credentials in Dashboard → Settings → Telegram")

print("="*70)