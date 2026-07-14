#!/bin/bash
# INSTRUKSI RESTART MANUAL
# Jalankan command ini satu per satu di SSH terminal

echo "=== STEP 1: Stop semua process ==="
killall -9 python3

echo "=== STEP 2: Tunggu 2 detik ==="
sleep 2

echo "=== STEP 3: Start bot realtime ==="
cd /opt/crypto-quant-bot
nohup python run_realtime.py >> logs/bot.log 2>&1 &

echo "=== STEP 4: Start dashboard ==="
nohup python -m app.dashboard.app >> logs/dashboard.log 2>&1 &

echo "=== SELESAI ==="
echo "Cek status:"
echo "  tail -f logs/bot.log"
echo "  tail -f logs/dashboard.log"
echo "  curl http://localhost:8080/health"
