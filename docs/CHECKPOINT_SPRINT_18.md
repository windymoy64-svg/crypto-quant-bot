# Checkpoint Sprint 18

Status: completed.

Tanggal checkpoint: 2026-07-07.

## Goal

Sprint 18 menambahkan Analytics & Performance Engine untuk membaca data Event Bus, Paper Trading, Backtest, dan Portfolio tanpa mengubah logic trading.

## Architecture Review

### Event Bus Consumption

- `AnalyticsEventCollector` berperan sebagai subscriber pasif melalui `app.events.subscriber.subscribe()`.
- Collector subscribe ke `PaperOrderFilled`, `PaperPositionClosed`, `PaperBalanceUpdated`, `PositionClosed`, `PortfolioUpdated`, dan `BacktestFinished`.
- Event paper fill dinormalisasi menjadi trade journal berbasis FIFO lot matching.
- Event portfolio/balance dinormalisasi menjadi equity snapshots.
- Event backtest disimpan sebagai summary input tambahan tanpa memicu order, risk check, atau signal baru.

### Files Modified / Created

- `app/analytics/__init__.py`
- `app/analytics/performance.py`
- `app/analytics/statistics.py`
- `app/analytics/journal.py`
- `app/analytics/reports.py`
- `app/analytics/equity.py`
- `app/analytics/attribution.py`
- `configs/analytics.json`
- `docs/CHECKPOINT_SPRINT_18.md`

### Why No Trading Logic Changes Are Required

- Paper Trading sudah menyimpan orders/fills/state dan menerbitkan event paper.
- Backtest sudah menghasilkan trades, equity curve, dan `BacktestFinished`.
- Portfolio sudah menerbitkan `PortfolioUpdated`, `PositionOpened`, dan `PositionClosed`.
- Analytics hanya membaca event/artifact yang sudah ada, lalu menghitung journal, metrics, attribution, dan summaries.
- Rule Engine, Scanner, Risk Engine, Execution, Exchange, dan Market Data tidak perlu disentuh.

## Fitur Utama

- Trade journal dari backtest trades dan paper fills.
- Performance metrics: win rate, profit factor, Sharpe ratio, Sortino ratio, Calmar ratio, recovery factor, drawdown, expectancy, gross/net PnL.
- Regime performance.
- Pair performance.
- Rule attribution.
- Daily, weekly, dan monthly summary.
- Batch report builder dari paper state/events dan backtest result files.
- Event Bus collector untuk analytics runtime pasif.

## Safety Boundary

- Tidak mengubah Rule Engine.
- Tidak mengubah Scanner.
- Tidak mengubah Risk Engine.
- Tidak mengubah Execution.
- Tidak mengubah Exchange.
- Tidak mengubah Market Data.
- Tidak menjalankan pytest sesuai instruksi Sprint 18.

## Verification

- `python -m compileall app`

## Known Limitations

- Paper trade journal memakai FIFO matching dari fills; partial close kompleks mengikuti urutan fill yang tersedia.
- Rule attribution hanya terisi bila input trade/event membawa daftar rules di metadata.
- Regime performance default `unknown` bila input tidak membawa market regime.
- Paper state saat ini tidak menyimpan historical equity curve penuh, sehingga equity dari state hanya snapshot terakhir kecuali Event Bus collector aktif.
- Analytics belum memiliki CLI runner khusus; report dapat dibuat lewat `AnalyticsEngine`.

## Remaining TODO

- Sprint 18 selesai.
- Sprint 19 belum dimulai.