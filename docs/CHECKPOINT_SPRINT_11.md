# Checkpoint Sprint 11

Status: completed.

Tanggal checkpoint: 2026-07-07.

## Goal

Sprint 11 menambahkan Execution Simulator Layer dan mengintegrasikannya hanya ke Historical Backtest Engine.

## Fitur Utama

- Model order lifecycle: `NEW`, `PARTIALLY_FILLED`, `FILLED`, `CANCELLED`, dan `REJECTED`.
- Maker/taker fee model.
- Spread model berbasis basis points.
- Slippage model berbasis basis points.
- Latency model berbasis jumlah candle delay.
- Partial fill simulation berbasis volume candle dan fill ratio.
- Backtest entry/exit sekarang lewat `ExecutionSimulator`, bukan kalkulasi fee langsung.

## File Dibuat

- `app/execution/order.py` untuk order, enum side/type/status/liquidity, dan lifecycle event.
- `app/execution/fill.py` untuk fill result dan simulated fill.
- `app/execution/fee.py` untuk maker/taker fee model.
- `app/execution/slippage.py` untuk spread dan slippage model.
- `app/execution/latency.py` untuk candle-delay execution model.
- `app/execution/simulator.py` untuk simulated market order execution.

## File Diintegrasikan

- `app/backtest/simulator.py` sekarang menggunakan `ExecutionSimulator` untuk order BUY/SELL.
- `app/backtest/engine.py` menambahkan execution settings pada `BacktestConfig` dan meneruskannya ke simulator.
- `run_backtest.py` menambahkan argumen CLI untuk fee, slippage, spread, latency, dan partial fill.

## Safety Boundary

- Tidak ada live trading.
- Tidak ada API key.
- Tidak ada Portfolio implementation.
- Tidak mengubah Rule Engine.
- Tidak mengubah Scanner.
- Tidak mengubah MarketData.
- `app/execution/live_executor.py` tidak disentuh.

## Verification

- `python -m compileall app`

## Sprint Berikutnya

Sprint 12 belum dimulai.