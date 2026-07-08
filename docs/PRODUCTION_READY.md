# Production Ready Guide

This guide covers the final hardening state for production deployment. It does not introduce new trading features or change trading business logic.

## Deployment

- Build with Docker: `docker compose build`.
- Start services: `docker compose up -d api realtime`.
- Keep the published dashboard port bound to localhost unless a hardened reverse proxy is in front of it: `127.0.0.1:8899:8899`.
- Use `deploy/nginx.conf` as the reverse proxy baseline for gzip, static caching, websocket upgrade, security headers, body limits, and proxy timeouts.
- Confirm service health with `curl http://127.0.0.1:8899/health`.

## Environment

- Copy `.env.example` to `.env` and set deployment-specific values.
- Set `BOT_API_KEY` to a long random token before exposing the dashboard/API beyond localhost.
- Keep `LIVE_TRADING_ENABLED=false` and `LIVE_TRADING_DRY_RUN=true` until exchange, account, and risk checks are fully validated.
- Docker overrides `BOT_API_HOST=0.0.0.0` inside the container while binding the host port to localhost.
- Runtime startup validates and creates `logs/`, `data/`, `configs/`, and `logs/backtests/` safely.

## Dependency Management

- Runtime dependencies are pinned in `requirements.txt`.
- `requirements-lock.txt` captures the installed transitive dependency set for reproducible rebuilds.
- `websocket-client` is explicitly included because Binance realtime websocket support imports it at runtime.

## Logging

- Production logging writes JSON lines to `logs/bot.log`.
- Warnings rotate daily in `logs/warning.log`.
- Errors rotate daily in `logs/error.log`.
- Logs retain 14 daily backups by default.
- Container stdout also receives JSON logs for Docker log collection.

## Health And Monitoring

- `/health` remains public for local Docker/nginx health checks.
- `/api/*` is protected when `BOT_API_KEY` exists.
- `/ws` is protected when `BOT_API_KEY` exists and accepts `?api_key=<BOT_API_KEY>` or `?token=<BOT_API_KEY>`.
- Health payload includes uptime, CPU process time, memory availability where supported, disk usage, SQLite status, websocket status, exchange configuration status, and Binance connectivity state.
- Binance connectivity is reported as configured/not-configured without making network calls from the health endpoint.

## SQLite

- SQLite market history uses WAL mode, `busy_timeout=30000`, and `synchronous=NORMAL`.
- Shutdown performs a WAL checkpoint when the history database exists.
- Back up `data/market_history.sqlite3` together with any `-wal` and `-shm` files while services are stopped, or after a checkpoint.

## Backup

- Stop services: `docker compose stop api realtime`.
- Copy `data/`, `logs/`, `configs/`, `.env`, and `requirements-lock.txt` to backup storage.
- Restart services: `docker compose up -d api realtime`.

## Restore

- Stop services before restore.
- Restore `data/`, `logs/`, `configs/`, and `.env` into the project root.
- Rebuild if dependency files changed: `docker compose build`.
- Start services and check `/health`.

## Troubleshooting

- API does not respond: check `docker compose ps`, container logs, and `BOT_API_PORT`.
- Dashboard 401: set `Authorization: Bearer <BOT_API_KEY>` for API clients or unset the key for localhost-only development.
- Websocket closes with policy violation: pass `?api_key=<BOT_API_KEY>` when API key protection is enabled.
- SQLite locked: verify only expected services write to `data/`, check disk latency, and confirm WAL is enabled in `/health`.
- Binance websocket import failure: reinstall from pinned `requirements.txt` or `requirements-lock.txt`.

## Maintenance

- Rotate and archive logs under `logs/` according to disk capacity.
- Review `/health` daily for disk pressure, SQLite status, and exchange configuration.
- Keep `.env` out of source control.
- Test dependency upgrades in staging, then regenerate `requirements-lock.txt`.

## Upgrade Guide

- Stop services: `docker compose stop api realtime`.
- Back up `data/`, `logs/`, `configs/`, `.env`, and lock files.
- Pull or apply code changes.
- Rebuild: `docker compose build`.
- Run verification: `python -m compileall app` and `pytest`.
- Start services and validate `/health` before enabling live execution.

## Production Readiness Checklist

- [x] Runtime dependencies pinned.
- [x] `requirements-lock.txt` generated.
- [x] Docker runs as non-root user.
- [x] Docker healthcheck configured.
- [x] Docker restart policy, timezone, volumes, and resource limits configured.
- [x] Nginx gzip, security headers, static cache, websocket upgrade, body limit, and proxy timeouts configured.
- [x] JSON rotating logs configured for app, warning, and error logs.
- [x] SQLite WAL, busy timeout, and shutdown checkpoint configured.
- [x] `/api/*` and `/ws` protected when `BOT_API_KEY` exists.
- [x] Runtime directories are created safely.
- [x] Startup prints Python version, bot version, exchange, dashboard port, mode, and SQLite path.
- [x] Health endpoint includes uptime, CPU, memory, SQLite, websocket, and Binance configuration state.
- [x] CTRL+C, SIGTERM, and Docker stop paths trigger graceful shutdown hooks.

## Known Limitations

- The health endpoint intentionally avoids live Binance network calls to prevent health checks from blocking on exchange/network latency.
- Browser websocket clients cannot set Authorization headers directly; use query token protection or reverse-proxy auth for `/ws`.
- `logs/` and `data/` are local-volume based; high-availability deployments should move state and log aggregation to managed infrastructure.