import sys, os
sys.path.insert(0, '.')
from app.settings.telegram_preferences import load_telegram_preferences
prefs = load_telegram_preferences()
print("=== TELEG RAM CONFIG STATUS ===")
print(f"Enabled: {prefs.enabled}")
print(f"Token: {prefs.bot_token_masked or '(empty)'}")
print(f"Chat ID: {prefs.chat_id_masked or '(empty)'}")
if prefs.enabled:
    print("\n✅ SETTINGS SAVED IN DATABASE!")
    print("To ACTIVATE: Set env vars and restart service")
else:
    print("\n❌ NOT CONFIGURED")
