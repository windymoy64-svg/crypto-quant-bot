#!/bin/bash

# Kill existing processes
pkill -f run_realtime || true
pkill -f run_live || true

# Wait untuk graceful shutdown
sleep 2

# Start bot dengan systemd atau direct
cd /opt/crypto-quant-bot

# Check if systemd service exists
if systemctl is-active --quiet crypto-quant-bot; then
    echo "Restarting via systemctl..."
    systemctl restart crypto-quant-bot
else
    echo "Starting bot directly..."
    nohup python run_realtime.py >> logs/bot.log 2>&1 &
    echo $! > logs/bot.pid
fi

echo "Bot restarted. Checking status..."
sleep 3

if [ -f logs/paper_state.json ]; then
    echo "✓ Paper state file exists"
    echo "Open positions:"
    python -c "import json; print(len(json.load(open('logs/paper_state.json')).get('open_positions', {})))"
fi

if [ -f logs/bot.log ]; then
    echo ""
    echo "Latest logs:"
    tail -20 logs/bot.log
fi
