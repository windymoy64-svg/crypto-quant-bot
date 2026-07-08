# Checkpoint Sprint 19

Status: completed.

Tanggal checkpoint: 2026-07-07.

## Goal

Sprint 19 menambahkan FastAPI Dashboard Control Center yang read-only untuk menampilkan Market, Portfolio, Paper Account, Analytics, Trade Journal, Open Positions, dan Live Events.

## Architecture Review

### Dashboard Event Bus Subscription

- `app/dashboard/websocket.py` menyediakan `DashboardEventHub` sebagai subscriber pasif ke Event Bus.
- Saat WebSocket pertama tersambung, hub melakukan `subscribe("*", self.handle_event)` agar semua event runtime bisa masuk ke live event stream.
- Event yang diterima dikonversi memakai `event.to_dict()` bila tersedia, disimpan di ring buffer, lalu dibroadcast ke semua koneksi WebSocket aktif.
- WebSocket juga mengirim snapshot awal dari `DashboardService.snapshot()` agar UI langsung terisi sebelum event baru muncul.

### Why Dashboard Must Not Call Rule Engine Directly

- Dashboard adalah read-only presentation layer, bukan decision pipeline.
- Rule Engine adalah bagian dari alur signal/risk/trading; memanggilnya dari dashboard dapat membuat UI ikut menghasilkan keputusan trading.
- Direct call ke Rule Engine berisiko side effect, coupling, dan hasil yang tidak sinkron dengan scanner/backtest/paper pipeline resmi.
- Dashboard hanya membaca artifact dan event yang sudah dipublikasikan oleh Market, Portfolio, Analytics, Paper Trading, dan Backtest.

### Files Modified / Created

- `app/dashboard/app.py`
- `app/dashboard/api.py`
- `app/dashboard/websocket.py`
- `app/dashboard/services.py`
- `app/dashboard/routes/__init__.py`
- `app/dashboard/routes/market.py`
- `app/dashboard/routes/portfolio.py`
- `app/dashboard/routes/analytics.py`
- `app/dashboard/routes/paper.py`
- `app/dashboard/routes/backtest.py`
- `app/dashboard/routes/health.py`
- `app/dashboard/templates/index.html`
- `app/dashboard/static/dashboard.css`
- `app/dashboard/static/dashboard.js`
- `docs/CHECKPOINT_SPRINT_19.md`

## REST API

- `GET /api/market`
- `GET /api/portfolio`
- `GET /api/paper`
- `GET /api/backtest`
- `GET /api/analytics`
- `GET /api/health`

Legacy compatibility retained:

- `GET /health`
- `GET /status`
- `GET /signals/latest`
- `GET /paper/state`

## WebSocket

- `GET /ws` via WebSocket upgrade.
- Sends initial snapshot.
- Streams live Event Bus updates.
- Maintains recent live events ring buffer.

## Safety Boundary

- No trading buttons.
- No BUY.
- No SELL.
- No Cancel.
- No direct Rule Engine calls.
- No order/execution/risk mutation.
- Dashboard is read-only.

## Verification

- `python -m compileall app`

## Known Limitations

- Live events only stream while dashboard process shares the same in-memory Event Bus as publishers.
- Historical analytics report is generated on read if `logs/analytics_report.json` is missing, but it is not persisted by the dashboard.
- Paper equity history remains limited by available paper state/events and backtest artifacts.
- REST authentication follows existing `BOT_API_KEY` bearer behavior; the static UI assumes no `BOT_API_KEY` for browser reads.

## Remaining TODO

- Sprint 19 selesai.
- Sprint 20 belum dimulai.