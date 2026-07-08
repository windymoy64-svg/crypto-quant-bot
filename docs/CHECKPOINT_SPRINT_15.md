# Checkpoint Sprint 15

Status: completed.

Tanggal checkpoint: 2026-07-07.

## Goal

Sprint 15 menambahkan Realtime Binance WebSocket Engine read-only.

## Fitur Utama

- Combined websocket stream builder.
- Kline stream.
- Mini ticker stream.
- Book ticker stream.
- Depth stream.
- Aggregate trade stream.
- Multiple symbol subscription.
- Event callbacks: `on_kline`, `on_ticker`, `on_book`, `on_trade`, `on_depth`, `on_message`, `on_error`, `on_open`, dan `on_close`.
- Auto reconnect dengan exponential backoff.
- Auto resubscribe lewat rebuild combined stream dari subscription aktif.
- Heartbeat configuration untuk ping interval dan stale tracking.

## Architecture Updates

- `app/exchange/binance/websocket.py` sekarang menjadi engine websocket read-only.
- `app/exchange/binance/subscription.py` memisahkan pembuatan stream name dan combined stream subscription.
- `app/exchange/binance/stream.py` memisahkan callback model dan event dispatcher.
- `app/exchange/binance/heartbeat.py` memisahkan state heartbeat.
- `app/exchange/binance/reconnect.py` memisahkan reconnect/backoff policy.
- `MarketDataService` menyediakan factory `create_realtime_stream()` untuk membuat Binance realtime stream tanpa mengubah scanner.

## Files Changed

- `app/exchange/binance/websocket.py`
- `app/exchange/binance/stream.py`
- `app/exchange/binance/subscription.py`
- `app/exchange/binance/heartbeat.py`
- `app/exchange/binance/reconnect.py`
- `app/market/data_service.py`
- `docs/CHECKPOINT_SPRINT_15.md`

## Safety Boundary

- Tidak mengubah Rule Engine.
- Tidak mengubah Risk Engine.
- Tidak mengubah Portfolio.
- Tidak mengubah Execution.
- Tidak mengubah Backtest.
- Tidak mengubah Live Trading.
- Tidak menambahkan order placement.
- Tidak menambahkan API write.

## Verification

- `python -m compileall app`

## Known Limitations

- Runtime websocket membutuhkan package optional `websocket-client`.
- Tidak menjalankan network smoke test agar checkpoint tidak membuka koneksi eksternal.
- Heartbeat saat runtime bergantung pada `websocket-client` ping loop; stale tracking tersedia untuk observability.

## Sprint Berikutnya

Sprint 16 belum dimulai.