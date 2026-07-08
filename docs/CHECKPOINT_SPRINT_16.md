# Checkpoint Sprint 16

Status: completed.

Tanggal checkpoint: 2026-07-07.

## Goal

Sprint 16 menambahkan Internal Event Bus untuk komunikasi event sinkron di dalam aplikasi.

## Fitur Utama

- `publish(event)` untuk menerbitkan event internal.
- `subscribe(event_type, handler)` untuk mendaftarkan handler berdasarkan class event, nama event, atau wildcard `*`.
- `unsubscribe(event_type, handler)` untuk melepas handler.
- In-memory synchronous event bus dengan lock ringan untuk operasi subscriber.

## Event Models

- `PriceUpdated`
- `SignalCreated`
- `RiskApproved`
- `RiskRejected`
- `OrderCreated`
- `OrderFilled`
- `PositionOpened`
- `PositionClosed`
- `PortfolioUpdated`
- `BacktestFinished`

## Integrasi

- `MarketDataService` menerbitkan `PriceUpdated` saat ticker berhasil diperoleh.
- Backtest menerbitkan `SignalCreated` dan `BacktestFinished`.
- Risk menerbitkan `RiskApproved` dan `RiskRejected`.
- Execution simulator menerbitkan `OrderCreated` dan `OrderFilled`.
- Portfolio menerbitkan `PositionOpened`, `PositionClosed`, dan `PortfolioUpdated`.

## Files Changed

- `app/events/__init__.py`
- `app/events/bus.py`
- `app/events/events.py`
- `app/events/publisher.py`
- `app/events/subscriber.py`
- `app/market/data_service.py`
- `app/backtest/engine.py`
- `app/backtest/simulator.py`
- `app/risk/manager.py`
- `app/portfolio/manager.py`
- `app/execution/simulator.py`
- `docs/CHECKPOINT_SPRINT_16.md`

## Safety Boundary

- Tidak mengubah Rule Engine.
- Tidak mengubah Dynamic Weight.
- Tidak mengubah Feature Builder.
- Tidak mengubah Scanner logic.
- Tidak mengubah Exchange Connector.
- Tidak menambahkan Telegram integration.
- Tidak menambahkan Dashboard integration.
- Tidak mengubah Live Trading.

## Verification

- `python -m compileall app`

## Known Limitations

- Event bus masih in-memory dan sinkron, belum persistent queue.
- Handler exception belum diisolasi; exception dari subscriber akan ikut naik ke caller.
- Belum ada metrics, tracing, atau replay event.

## Sprint Berikutnya

Sprint 17 belum dimulai.