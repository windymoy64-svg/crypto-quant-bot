# Checkpoint Sprint 12

Status: completed.

Tanggal checkpoint: 2026-07-07.

## Goal

Sprint 12 menambahkan Risk Management Engine dan mengintegrasikannya hanya ke Historical Backtest Engine serta jalur Execution Simulator.

## Fitur Utama

- Position sizing berbasis persen risiko per trade.
- Maximum exposure guard.
- Maximum open positions guard.
- Daily drawdown protection.
- ATR volatility filter.
- Risk/reward validation.
- Trade approval dan rejection decision.
- JSON risk output pada hasil backtest.

## File Dibuat

- `app/risk/position_size.py` untuk perhitungan ukuran posisi berbasis risiko.
- `app/risk/stoploss.py` untuk validasi stop loss long.
- `app/risk/takeprofit.py` untuk validasi risk/reward.
- `app/risk/exposure.py` untuk batas exposure dan open positions.
- `app/risk/drawdown.py` untuk daily drawdown protection.
- `app/risk/volatility.py` untuk ATR volatility filter.

## File Diubah

- `app/risk/manager.py` menjadi risk orchestration layer dan tetap mempertahankan fungsi lama `calculate_position_size`.
- `app/backtest/simulator.py` mengevaluasi BUY signal melalui `RiskManager` sebelum order dikirim ke `ExecutionSimulator`.
- `app/backtest/engine.py` menambahkan konfigurasi risk dan output JSON risk.
- `run_backtest.py` menambahkan argumen CLI untuk konfigurasi risk.

## Safety Boundary

- Tidak mengubah Rule Engine.
- Tidak mengubah Scanner.
- Tidak mengubah Market Data.
- Tidak mengubah Feature Builder.
- Tidak mengubah Scoring Engine.
- Tidak mengubah Multi Timeframe.
- Tidak mengubah Portfolio.
- Tidak mengubah Paper Trading.
- Tidak mengubah Live Trading.

## Verification

- `python -m compileall app`

## Sprint Berikutnya

Sprint 13 belum dimulai.