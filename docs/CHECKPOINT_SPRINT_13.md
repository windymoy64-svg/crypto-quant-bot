# Checkpoint Sprint 13

Status: completed.

Tanggal checkpoint: 2026-07-07.

## Goal

Sprint 13 menambahkan Portfolio Engine dan mengintegrasikannya hanya ke Historical Backtest Engine serta Risk Engine path.

## Fitur Utama

- Account balance tracking.
- Equity calculation.
- Available balance.
- Used capital.
- Open positions.
- Realized PnL.
- Unrealized PnL.
- ROI.
- Exposure per symbol.
- Portfolio summary JSON pada hasil backtest.

## File Dibuat

- `app/portfolio/account.py` untuk model account portfolio.
- `app/portfolio/balance.py` untuk cash, available balance, dan realized PnL.
- `app/portfolio/position.py` untuk open position dan unrealized PnL.
- `app/portfolio/exposure.py` untuk exposure per symbol.
- `app/portfolio/performance.py` untuk total PnL dan ROI.
- `app/portfolio/manager.py` untuk portfolio orchestration dan summary JSON.

## File Diubah

- `app/backtest/simulator.py` menggunakan `PortfolioManager` sebagai sumber equity, available balance, open positions, dan exposure untuk Risk Engine.
- `app/backtest/engine.py` menambahkan portfolio summary ke output `BacktestResult`.

## Safety Boundary

- Tidak mengubah Rule Engine.
- Tidak mengubah Scanner.
- Tidak mengubah Market Data.
- Tidak mengubah Feature Builder.
- Tidak mengubah Multi Timeframe.
- Tidak mengubah Execution Simulator.
- Tidak mengubah Paper Trading.
- Tidak mengubah Live Trading.

## Verification

- `python -m compileall app`

## Sprint Berikutnya

Sprint 14 belum dimulai.