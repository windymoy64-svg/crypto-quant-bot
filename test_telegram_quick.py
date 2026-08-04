#!/usr/bin/env python3
"""Quick one-click Telegram connection test."""
import sys
sys.path.insert(0, '/opt/crypto-quant-bot')

print("="*70)
print("🚀 TELEGRAM QUICK TEST")
print("="*70)

# Load settings from encrypted store
from app.settings.telegram_preferences import load_telegram_preferences

prefs = load_telegram_preferences()

if not prefs.enabled or not prefs.bot_token_masked or not prefs.chat_id_masked:
    print("\n❌ NOT CONFIGURED")
    print("Please enter Bot Token & Chat ID in Dashboard → Settings → Telegram")
    sys.exit(1)

print(f"\n✅ Configuration found:")
print(f"   Enabled: {prefs.enabled}")
print(f"   Token: {prefs.bot_token_masked}")
print(f"   Chat ID: {prefs.chat_id_masked}")

# Check if environment variables are already set (runtime will use these)
import os
token = os.getenv('TELEGRAM_BOT_TOKEN', '')
chat_id = os.getenv('TELEGRAM_CHAT_ID', '')

if token and chat_id:
    print(f"\n✓ Environment variables found - ready to send message")
else:
    print(f"\n⚠️  Environment variables NOT set yet")
    print(f"   Credentials saved in database but runtime hasn't loaded them yet.")
    print(f"\n💡 Quick activation options:\n")
    print(f"Option A - Set env vars temporarily (for testing):")
    print(f"   export TELEGRAM_BOT_TOKEN='paste_your_real_token'")
    print(f"   export TELEGRAM_CHAT_ID='paste_your_chat_id'")
    print(f"   cd /opt/crypto-quant-bot && python test_telegram_quick.py\n")
    print(f"Option B - Permanent setup:")
    print(f"   sudo nano /etc/systemd/system/crypto-quant-bot.env.d/telegram.conf")
    print(f"   Add lines with TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")
    print(f"   sudo systemctl daemon-reload && sudo systemctl restart crypto-quant-bot\n")
    
    # Show masked values as confirmation they ARE saved
    print(f"{"="*70}")
    print(f"✅ YOUR SETTINGS ARE SAVED in secure database:")
    print(f"   You can verify by checking dashboard at port 8899")
    print(f"   Go to Settings → Telegram tab")
    print(f"   Your bot_token shows as ...y9uY (masked)")
    print(f"   Your chat_id shows as ...9456 (masked)")
    print(f"{'='*70}")
    
    choice = input("\nWould you like to set env vars now and test? (y/n): ").strip().lower()
    if choice != 'y':
        print("\nNo problem! Follow the instructions above to activate later.")
        sys.exit(0)
    
    # Get user input for temporary test
    print("\nPaste your bot token from @BotFather:")
    token = input("> ").strip()
    
    print("Paste your chat ID number:")
    chat_id = input("> ").strip()
    
    if not token or not chat_id:
        print("Tokens cannot be empty!")
        sys.exit(1)
    
    # Set temporarily for this session
    os.environ['TELEGRAM_BOT_TOKEN'] = token
    os.environ['TELEGRAM_CHAT_ID'] = chat_id

print(f"\n✓ Ready to send test message...")

# Send test message
print("-"*70)
print("📨 SENDING TEST MESSAGE TO TELEGRAM...")
print("-"*70)

import json
import urllib.request
import time

message = """🔔 *CRYPTO QUANT BOT - CONNECTION TEST*

✅ System check successful!

Your Telegram notifications are configured and ready.

What you'll receive automatically:
• 🟢 Entry signals with full details
• 🟡 Partial closes (TP1/TP2 hits)
• 🔴 Full closes with P&L summary

When bot executes trades, you'll see detailed reports here.

---
Generated: {}""".format(time.strftime('%Y-%m-%d %H:%M:%S'))

url = f"https://api.telegram.org/bot{token}/sendMessage"

payload = json.dumps({
    "chat_id": chat_id,
    "text": message,
    "parse_mode": "Markdown"
}).encode('utf-8')

req = urllib.request.Request(
    url,
    data=payload,
    headers={"Content-Type": "application/json"}
)

try:
    with urllib.request.urlopen(req, timeout=15) as response:
        result = json.loads(response.read().decode())
        
        if result.get('ok'):
            msg_data = result.get('result', {})
            
            print(f"\n{'='*70}")
            print(f"✅ SUCCESS! MESSAGE DELIVERED!")
            print(f"{'='*70}\n")
            
            print(f"📊 Delivery details:")
            print(f"   • Message ID: {msg_data.get('message_id')}")
            print(f"   • Chat: {msg_data.get('chat', {}).get('id')}")
            print(f"   • From: {msg_data.get('from', {}).get('username', 'Unknown')}")
            
            print(f"\n{'='*70}")
            print(f"🎉 CHECK YOUR TELEGRAM APP NOW!")
            print(f"   You should see the test message above within seconds.")
            print(f"{'='*70}")
            
            print(f"\n💡 Next trade entry will trigger automatic notification too.")
            
        else:
            print(f"\n❌ Telegram API Error:")
            print(f"   Code: {result.get('error_code')}")
            print(f"   Description: {result.get('description')}")
            
except Exception as e:
    print(f"\n❌ Failed to send message")
    print(f"   Error: {type(e).__name__}: {str(e)}")
    print(f"\n💡 Troubleshooting:")
    print(f"   1. Verify token is valid (check @BotFather)")
    print(f"   2. Send /start to your bot in Telegram first")
    print(f"   3. Check internet connection")
    print(f"   4. Ensure chat_id matches your account")

print("\n" + "="*70)
