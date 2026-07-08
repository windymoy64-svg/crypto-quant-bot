# Final Release Checkpoint

## Scope

- Portfolio sync now persists `logs/portfolio_state.json`, supports recovery, and reconciles filled order quantities against open positions.
- Telegram control center exposes safe read-only commands: `/status`, `/portfolio`, `/orders`, `/signals`, `/pnl`, `/start`, `/stop`, `/restart`, `/help`.
- Dashboard is a read-only professional operations shell with scanner, portfolio, orders, positions, analytics, journal, event stream, health, responsive navigation, WebSocket updates, and chart placeholders.
- Monitoring health reports API, exchange, websocket, disk, RAM, latency, and artifact availability.
- Production assets include Dockerfile, docker-compose, nginx reverse proxy config, and existing systemd units.

## Safety Gates

- Dashboard intentionally has no BUY, SELL, or Cancel buttons.
- `LIVE_TRADING_ENABLED=false` and `LIVE_TRADING_DRY_RUN=true` remain the recommended defaults.
- Exchange keys should never include withdrawal permission.
- Public API exposure should require `BOT_API_KEY`, firewall rules, or an SSH tunnel.

## Verification

```bash
python -m compileall app
pytest
python run_api.py
```

Open `http://127.0.0.1:8899` for the dashboard after starting the API.
