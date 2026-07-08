# Production Audit

Audit date: 2026-07-07

Scope: full project production-readiness review across structure, duplicated/dead code indicators, exception handling, logging, SQLite safety, websocket reconnect, thread/resource cleanup, API timeout/retry behavior, dashboard rendering, security/secrets handling, environment loading, Docker, nginx, and dependency versions.

Constraints followed: no new features, no UI redesign, no architecture changes, no public API changes, no business-logic changes. Only confirmed production bugs were fixed.

## Critical Issues

- None confirmed during this audit.

## High Priority

- Fixed: dashboard websocket broadcast resilience.
  - File: `app/dashboard/websocket.py`
  - Issue: broadcast/drain logic could terminate or retain stale websocket connections when send failures raised exceptions outside `RuntimeError`.
  - Impact: one bad client could degrade realtime dashboard delivery and leave stale connections in memory.
  - Fix: catch and log all send failures, remove stale connections, keep the drain loop alive, and clean up connections on non-disconnect exceptions.

- Fixed: dashboard websocket event-loop lifecycle safety.
  - File: `app/dashboard/websocket.py`
  - Issue: runtime queue/task was created once and did not safely reset if the app event loop changed, which can happen in tests, reloads, or multi-loop runtime setups.
  - Impact: events could be scheduled onto an unavailable loop, causing lost dashboard updates.
  - Fix: detect loop changes, cancel stale drain task, recreate queue, and guard `call_soon_threadsafe` with logging.

- Fixed: Binance websocket duplicate thread/resource leak risk.
  - File: `app/exchange/binance/websocket.py`
  - Issue: repeated `start()` calls could create multiple daemon websocket threads for the same instance.
  - Impact: duplicate subscriptions, duplicate callbacks, higher memory/thread usage, and harder shutdown behavior.
  - Fix: add a small lock, make repeated `start()` idempotent while running, close/join on `stop()`, and clear `_ws_app` after `run_forever()` exits.

- Fixed: SQLite concurrent access safety.
  - File: `app/market/storage.py`
  - Issue: SQLite connections used default timeout/journal behavior.
  - Impact: concurrent API/realtime reads and writes could fail with `database is locked` under normal production load.
  - Fix: set `timeout=30`, `PRAGMA busy_timeout=30000`, `PRAGMA journal_mode=WAL`, and `PRAGMA synchronous=NORMAL` for safer concurrent readers/writers.

## Medium Priority

- Dependency pinning is too broad.
  - Files: `requirements.txt`, `pyproject.toml`
  - Current state: runtime dependencies use lower bounds only (`>=`) and Python requires `>=3.13`.
  - Risk: non-reproducible builds and future dependency breakage.
  - Recommendation: lock production deployments with a generated constraints/lock file and test upgrades separately.

- Runtime dependency gap for websocket streams.
  - Files: `requirements.txt`, `app/exchange/binance/websocket.py`
  - Current state: code imports `websocket` from `websocket-client`, but `requirements.txt` does not explicitly include `websocket-client`.
  - Risk: realtime Binance websocket may fail in a clean production install unless pulled transitively by another package.
  - Recommendation: add an explicit runtime dependency after confirming deployment expectations.

- API authentication is optional by environment.
  - File: `app/dashboard/app.py`
  - Current state: `BOT_API_KEY` absence disables API key checks for protected routes.
  - Risk: unsafe if the API is exposed beyond localhost/reverse proxy without a key.
  - Recommendation: keep `BOT_API_HOST=127.0.0.1` for local-only deployments or require `BOT_API_KEY` in production environment validation.

- Websocket endpoint is not API-key protected.
  - File: `app/dashboard/app.py`
  - Current state: `/ws` is mounted without the `require_api_key` dependency.
  - Risk: event/snapshot visibility if reverse proxy exposes the service publicly.
  - Recommendation: protect at nginx/firewall layer or add websocket auth in a future API-compatible plan.

- Dashboard service reads full JSONL files into memory.
  - File: `app/dashboard/services.py`
  - Current state: `read_jsonl_file()` loads entire file before slicing to the requested limit.
  - Risk: memory and latency growth if log files become large.
  - Recommendation: switch to tail-style bounded reading in a dedicated performance pass.

- Public HTTP retry logic is limited.
  - File: `app/exchange/public_http_client.py`
  - Current state: public endpoints have a timeout but no retry/backoff in the client itself.
  - Risk: transient network or exchange errors can surface directly to callers.
  - Recommendation: add bounded retry/backoff at call sites or client layer after defining retry policy.

- Nginx websocket hardening is minimal.
  - File: `deploy/nginx.conf`
  - Current state: websocket proxy headers are present, but read/send timeouts and security headers are not configured.
  - Risk: long-lived connections can be closed unexpectedly by defaults; public deployments need additional headers/rate limiting.
  - Recommendation: add deployment-specific `proxy_read_timeout`, `proxy_send_timeout`, TLS, and security headers.

## Low Priority

- Project root is not a git repository in the audited workspace.
  - Observation: `git status --short` failed with `fatal: not a git repository`.
  - Risk: difficult change tracking and release provenance from this output directory.
  - Recommendation: run audit from the repository root or initialize source control for release artifacts.

- `rg` is not installed in the shell environment.
  - Observation: `rg --files` failed because `rg` is unavailable.
  - Risk: slower local audit/search workflows only.
  - Recommendation: optional developer tooling install; no runtime impact.

- Docker image runs as root by default.
  - File: `Dockerfile`
  - Risk: container hardening gap.
  - Recommendation: add a non-root user in a deployment-hardening pass after validating volume permissions.

- Docker base image and dependencies are not pinned by digest/version lock.
  - Files: `Dockerfile`, `requirements.txt`
  - Risk: rebuilds may drift.
  - Recommendation: pin image digest and dependency lock for production releases.

- Deployment compose lacks healthchecks.
  - File: `docker-compose.yml`
  - Risk: orchestrator cannot detect unhealthy app process beyond process exit.
  - Recommendation: add healthchecks against `/health` in deployment configuration.

- Duplicate/legacy documentation checkpoint files are numerous.
  - Files: `docs/CHECKPOINT_*.md`
  - Risk: repository noise, not runtime risk.
  - Recommendation: keep if used for project history; otherwise archive in a documentation cleanup pass.

## Recommendations

- Add explicit production lock/constraints files for Python dependencies.
- Add explicit `websocket-client` if realtime Binance streams are expected in clean production installs.
- Enforce `BOT_API_KEY` and TLS/proxy protection before exposing the dashboard/API beyond localhost.
- Add nginx timeouts and security headers for production reverse proxy deployments.
- Add Docker healthchecks and consider non-root container execution after validating file permissions.
- Add log rotation or bounded reads for JSON/JSONL dashboard artifacts.
- Consider structured logging configuration for long-running processes so websocket and exchange errors are retained consistently.
- Keep SQLite for lightweight local deployments; consider an external database only if concurrent writers or history volume grows beyond SQLite's intended workload.

## Verification

- `python -m compileall app`: passed.
- `pytest`: passed, 64 tests.
- Manual review covered:
  - `app/dashboard/websocket.py`
  - `app/dashboard/app.py`
  - `app/dashboard/services.py`
  - `app/market/storage.py`
  - `app/exchange/binance/websocket.py`
  - `app/exchange/public_http_client.py`
  - `app/config/env.py`
  - `app/events/bus.py`
  - `app/events/subscriber.py`
  - `requirements.txt`
  - `pyproject.toml`
  - `Dockerfile`
  - `docker-compose.yml`
  - `deploy/nginx.conf`
  - `.env.example`
