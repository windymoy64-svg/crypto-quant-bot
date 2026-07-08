# Checkpoint Sprint 10

Status: completed.

Tanggal checkpoint: 2026-07-06.

## Goal

Sprint 10 menambahkan Historical Backtest Engine yang memakai historical data dari Sprint 09, tanpa live trading, tanpa API key, tanpa Telegram, dan tanpa Dashboard.

## Fitur Utama

- Replay candle historis dari `HistoricalMarketDataEngine`.
- Feed candle window ke scoring pipeline existing yang memakai Feature Builder.
- Gunakan `ScoreEngine` existing dari `configs/rules.json`.
- Gunakan `build_signal` existing untuk membentuk signal per candle.
- Simulasi BUY/SELL long-only dengan stop loss, take profit, dan signal exit.
- Simpan trade round-trip.
- Bangun equity curve per candle.
- Hitung winrate, profit, max drawdown, sharpe, profit factor, average win, average loss, dan expectancy.
- Output console, JSON, trades CSV, dan equity CSV.

## File Dibuat

- `app/backtest/engine.py` untuk orchestration historical backtest.
- `app/backtest/simulator.py` untuk replay candle dan simulasi posisi.
- `app/backtest/trade.py` untuk model trade.
- `app/backtest/equity.py` untuk equity curve.
- `app/backtest/metrics.py` untuk metric backtest.
- `app/backtest/report.py` untuk output console, JSON, dan CSV.
- `run_backtest.py` untuk CLI backtest.

## Behavior

- Backtest mengambil candle melalui `HistoricalMarketDataEngine`.
- Jika public history tidak tersedia, downloader memakai sample candle sebagai fallback non-live.
- Dynamic rule weights bersifat opsional dan dilewati jika file weights tidak tersedia.
- Entry terjadi ketika signal existing menghasilkan `BUY`.
- Exit terjadi ketika stop loss tersentuh, take profit pertama tersentuh, signal berubah `SKIP`, atau candle terakhir tercapai.
- Semua output artifact default ditulis ke `logs/backtests/`.

## Safety Boundary

- Tidak ada live trading.
- Tidak ada API key.
- Tidak ada Telegram.
- Tidak ada Dashboard.
- Backtest hanya membaca data market publik atau sample fallback.

## Verification

- `python -m compileall app`

## Sprint Berikutnya

Sprint 11 belum dimulai. Kandidat fokus berikutnya adalah risk dashboard/alert atau peningkatan report backtest setelah Sprint 10 diterima.