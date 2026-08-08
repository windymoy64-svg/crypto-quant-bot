#!/usr/bin/env bash
set -Eeuo pipefail

cd /opt/crypto-quant-bot

echo "== API SERVICE =="
systemctl is-active crypto-quant-bot-api

echo
echo "== SCANNER SERVICE =="
systemctl is-active crypto-quant-bot

echo
echo "== PORT 8899 =="
ss -ltnp | grep ':8899' || {
  echo "FAIL: nothing is listening on port 8899"
  exit 1
}

echo
echo "== DASHBOARD/API VERIFY =="
./verify_dashboard_api.sh

echo
echo "PASS: production health check completed"