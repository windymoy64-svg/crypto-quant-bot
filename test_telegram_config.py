#!/usr/bin/env python3
"""Test actual Telegram connection."""
import sys
sys.path.insert(0, '/opt/crypto-quant-bot')

from app.settings.telegram_preferences import load_telegram_preferences
from app.telegram.notifier import TelegramNotifier
import json
import urllib.request
import os

print("="*70)
print("🚀 TESTING TELEGRAM API CONNECTION")
print("="*70)

# Load current settings
prefs = load_telegram_preferences()

if not prefs.enabled or not prefs.bot_token_masked or not prefs.chat_id_masked:
    print("\n❌ NOT CONFIGURED - please fill in Settings → Telegram first")
    sys.exit(1)

print(f"\n📋 Configuration loaded:")
print(f"   Enabled: {prefs.enabled}")
print(f"   Token masked: {prefs.bot_token_masked}")
print(f"   Chat ID masked: {prefs.chat_id_masked}")

# Load token/chat from secrets store (not just env)
token = os.getenv('TELEGRAM_BOT_TOKEN', '')
chat_id = os.getenv('TELEGRAM_CHAT_ID', '')

print(f"\n⚠️  Note: Environment variables from systemd might not be loaded yet.")
print(f"   To activate: restart service OR set TELEGRAM_ENABLED=true")

# Try to send test message using the notifier
print("\n" + "-"*70)
print("TESTING WITH NOTIFIER (reads from env vars)...")
print("-"*70)

notifier = TelegramNotifier(enabled=True, live=True)

print(f"\nNotifier token: {bool(notifier.token)}")
print(f"Notifer chat_id: {bool(notifier.chat_id)}")
print(f"Is configured: {notifier.is_configured}")

if notifier.is_configured:
    # Test sending
    message = "🔔 **CRYPTO BOT TEST**\n\n✅ Connection test successful!\nIf you receive this, Telegram is working."
    
    print(f"\n📨 Sending test message to chat {chat_id}...")
    
    # Direct API call for testing
    url = f"https://api.telegram.org/bot{notifier.token}/sendMessage"
    payload = json.dumps({
        "chat_id": notifier.chat_id,
        "text": message,
        "parse_mode": "Markdown"
    }).encode('utf-8')
    
    try:
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        
        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode())
            
            if result.get('ok'):
                print(f"\n{'='*70}")
                print(f"✅ SUCCESS! Message delivered to Telegram!")
                print(f"{'='*70}")
                print(f"\n📊 Response details:")
                print(f"   Message ID: {result.get('result', {}).get('message_id')}")
                print(f"   From: {result.get('result', {}).get('from', {}).get('username', 'Unknown')}")
                print(f"\n👉 CHECK YOUR TELEGRAM APP NOW FOR THE MESSAGE!")
                print(f"\n💡 When bot trades (entry/partial/full), you'll get detailed reports here.")
                
            else:
                print(f"\n❌ Telegram API returned error:")
                print(json.dumps(result, indent=2))
                
    except Exception as e:
        print(f"\n❌ Failed to send to Telegram API:")
        print(f"   Error: {str(e)}")
        print(f"\n💡 This could mean:")
        print(f"   1. Bot token invalid")
        print(f"   2. Chat ID incorrect")
        print(f"   3. Network issue")
        print(f"   4. Bot hasn't accepted your chat yet")
        print(f"\n🔧 Fix: In Telegram, start your bot and type /start first!")

else:
    print(f"\n⚠️  Credentials from environment are empty.")
    print(f"   This is expected if Telegram settings saved but .env not updated.")
    print(f"\n🔄 To test manually, you can set these temporarily:")
    print(f"   export TELEGRAM_BOT_TOKEN='your_token_here'")
    print(f"   export TELEGRAM_CHAT_ID='your_chat_id_here'")

print("\n" + "="*70)
