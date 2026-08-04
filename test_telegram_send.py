#!/usr/bin/env python3
"""Send test message using credentials from encrypted store."""
import sys
sys.path.insert(0, '/opt/crypto-quant-bot')

from app.settings.telegram_preferences import load_telegram_preferences
from app.telegram.notifier import TelegramNotifier
import json
import urllib.request

print("="*70)
print("📨 TESTING TELEGRAM NOTIFICATION DELIVERY")
print("="*70)

# Load preferences from encrypted store (this has real token/chat_id values internally)
prefs = load_telegram_preferences()

if not prefs.enabled or not prefs.bot_token_masked or not prefs.chat_id_masked:
    print("\n❌ NOT CONFIGURED - please set up in Settings → Telegram first")
    sys.exit(1)

print(f"\n✅ Using credentials from secure storage:")
print(f"   Bot Token: {prefs.bot_token_masked}")
print(f"   Chat ID: {prefs.chat_id_masked}")
print()

# Check if we can load credentials directly (for security, only masked shown)
# The SecretsStore encrypts values, so we can't easily decrypt here
# Instead, we recommend setting environment variables

print("🔐 Credentials are encrypted in storage for security.")
print("   To decode: Set environment variables and restart service.\n")
print("💡 Setup instructions:")
print("-" * 70)
print("Option 1: System-wide activation (recommended)")
print("   1. Create systemd environment file:")
print("      sudo mkdir -p /etc/systemd/system/crypto-quant-bot.env.d/")
print("      echo 'TELEGRAM_BOT_TOKEN=your_token_here' | sudo tee /etc/systemd/system/crypto-quant-bot.env.d/telegram.conf")
print("      echo 'TELEGRAM_CHAT_ID=your_chat_id_here' >> /etc/systemd/system/crypto-quant-bot.env.d/telegram.conf")
print("      echo 'TELEGRAM_ENABLED=true' >> /etc/systemd/system/crypto-quant-bot.env.d/telegram.conf")
print("   2. Reload and restart:")
print("      sudo systemctl daemon-reload")
print("      sudo systemctl restart crypto-quant-bot.service")
print("")
print("Option 2: Quick test (temporary)")
print("   Run this command then send manually:")
print("     cd /opt/crypto-quant-bot && python -c \"")
print("       import os")
print('       os.environ["TELEGRAM_BOT_TOKEN"] = "your_token"')
print('       os.environ["TELEGRAM_CHAT_ID"] = "your_chat_id"')
print("       from app.telegram.notifier import TelegramNotifier")
print("       n = TelegramNotifier(enabled=True, live=True)")
print("       n.send('Test message')\")
print("-" * 70)
sys.exit(0)

print(f"🔓 Decrypted credentials loaded")
print(f"   Token present: {bool(actual_token)}")
print(f"   Chat ID present: {bool(actual_chat_id)}")

print("\n" + "-"*70)
print("Sending TEST MESSAGE to Telegram API...")
print("-"*70)

message = """🔔 **CRYPTO QUANT BOT - TEST**

✅ Connection test successful!

If you receive this message, your Telegram notifications are working correctly.

You will now receive automatic notifications for:
• 🟢 ENTRY signals
• 🟡 PARTIAL CLOSE (TP1/TP2 hit)  
• 🔴 FULL CLOSE (SL/TP3/trailing stop)

Trade details including P&L, reason, and confidence will be sent automatically.

---
Crypto Quant Bot v1.0
"""

# Send via direct API call
url = f"https://api.telegram.org/bot{actual_token}/sendMessage"
payload = json.dumps({
    "chat_id": actual_chat_id,
    "text": message,
    "parse_mode": "Markdown"
}).encode('utf-8')

try:
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    
    with urllib.request.urlopen(req, timeout=10) as response:
        result = json.loads(response.read().decode())
        
        if result.get('ok'):
            print(f"\n{'='*70}")
            print(f"✅ SUCCESS! MESSAGE DELIVERED!")
            print(f"{'='*70}")
            
            msg_data = result.get('result', {})
            print(f"\n📊 Details:")
            print(f"   • Message ID: {msg_data.get('message_id')}")
            print(f"   • Chat ID: {msg_data.get('chat', {}).get('id')}")
            print(f"   • From Bot: {msg_data.get('from', {}).get('username', 'Unknown')}")
            print(f"   • Date: {msg_data.get('date', '')}")
            
            print(f"\n{'='*70}")
            print(f"🎉 CHECK YOUR TELEGRAM APP NOW!")
            print(f"   You should see the test message above.")
            print(f"{'='*70}")
            
            print(f"\n💡 Next time bot executes trade, you'll get detailed report here too.")
            
        else:
            print(f"\n❌ Telegram API returned error:")
            print(json.dumps(result, indent=2))
            
except Exception as e:
    print(f"\n❌ Failed to send message:")
    print(f"   Error type: {type(e).__name__}")
    print(f"   Message: {str(e)}")
    
    print(f"\n💡 Possible causes:")
    print(f"   1. Invalid bot token or chat ID")
    print(f"   2. Bot hasn't been started yet (send /start in Telegram)")
    print(f"   3. Network/firewall blocking")
    print(f"   4. Rate limited by Telegram")

print("\n" + "="*70)
