#!/bin/bash
# Quick restart - no checks, just force restart

cd /opt/crypto-quant-bot

# Force kill
killall -9 python3 2>/dev/null || true
sleep 1

# Start realtime bot
python run_realtime.py >> logs/bot.log 2>&1 &
echo "Bot started"

# Start dashboard (if not running)
python -m app.dashboard.app >> logs/dashboard.log 2>&1 &
echo "Dashboard started"

echo "Done. Check logs/bot.log and logs/dashboard.log"
