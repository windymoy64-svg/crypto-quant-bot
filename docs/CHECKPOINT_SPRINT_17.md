# Checkpoint Sprint 17

Status: completed.

Tanggal checkpoint: 2026-07-07.

## Goal

Sprint 17 menambahkan Paper Trading Engine yang menjalankan siklus simulasi order tanpa Live Trading dan tanpa Binance POST endpoint.

## Architecture Review

### Existing Modules Reused

- `MarketDataService` untuk mengambil OHLCV dan menyediakan factory Binance WebSocket.
- `BinanceWebSocket` melalui `MarketDataService.create_realtime_stream()` untuk integrasi stream tanpa order real.
- `ScoreEngine` untuk Rule Engine dan Dynamic Weight.
- `build_signal()` dari `app.signals.builder` untuk membangun sinyal trading dari score existing.
- `RiskManager` untuk approval/rejection entry.
- `PortfolioManager` untuk balance, posisi, equity, exposure, dan PnL.
- `ExecutionSimulator` untuk simulasi market order, fee, slippage, spread, latency, dan fill.
- `Event Bus` melalui `publish(...)` untuk event paper trading.

### Files Modified / Created

- `app/events/events.py`
- `app/paper/__init__.py`
- `app/paper/account.py`
- `app/paper/orders.py`
- `app/paper/positions.py`
- `app/paper/fills.py`
- `app/paper/persistence.py`
- `app/paper/engine.py`
- `configs/paper.json`
- `run_paper.py`
- `docs/CHECKPOINT_SPRINT_17.md`

### Event Bus Integration

- `PaperOrderCreated` diterbitkan saat paper order dibuat.
- `PaperOrderFilled` diterbitkan saat simulator menghasilkan fill.
- `PaperPositionOpened` diterbitkan setelah portfolio membuka posisi paper.
- `PaperPositionClosed` diterbitkan setelah portfolio menutup posisi paper.
- `PaperBalanceUpdated` diterbitkan setelah state portfolio selesai disimpan.
- Paper engine tetap menerima event existing dari modul reuse: `SignalCreated`, `RiskApproved` / `RiskRejected`, `OrderCreated` / `OrderFilled`, dan `PortfolioUpdated`.

## Fitur Utama

- Paper engine menjalankan satu siklus scan/simulate via `PaperTradingEngine.run_once()`.
- Konfigurasi default tersedia di `configs/paper.json`.
- Runner CLI tersedia di `run_paper.py`.
- State persistence menyimpan balance, positions, orders, dan fills.
- Event log JSONL menyimpan order/fill paper events.

## Safety Boundary

- Tidak ada Live Trading.
- Tidak ada Binance POST endpoint.
- Tidak ada real orders.
- Tidak menduplikasi logic scoring, risk, portfolio, dan execution.
- Tidak menjalankan pytest sesuai instruksi Sprint 17.

## Verification

- `python -m compileall app`

## Known Limitations

- Engine saat ini menjalankan satu siklus `run_once()`, belum loop daemon continuous.
- WebSocket baru disediakan sebagai factory helper, belum dihubungkan ke event loop paper secara penuh.
- Persistence masih file JSON/JSONL lokal, belum transactional database.
- Paper order id hanya counter runtime sehingga reset saat proses baru; state tetap menyimpan riwayat order sebelumnya.
- Dynamic weight dipakai saat `market_regime` diberikan di config; default config belum melakukan auto-detect regime.

## Remaining TODO

- Sprint 17 selesai.
- Sprint 18 belum dimulai.