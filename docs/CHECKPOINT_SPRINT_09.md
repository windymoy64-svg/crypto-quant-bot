# Checkpoint Sprint 09

Status: completed.

Tanggal checkpoint: 2026-07-06.

## Goal

Sprint 09 menambahkan Historical Market Data Engine tanpa live trading, tanpa API key, dan tanpa refactor modul yang sudah selesai.

## Fitur Utama

- Download OHLCV history melalui jalur market data publik yang sudah ada.
- Local cache untuk candle historis.
- SQLite storage di `data/market_history.sqlite3`.
- Automatic cache expiration berbasis TTL.
- History loader yang mengembalikan data cache jika masih valid.
- Scanner transparan memakai cached data melalui `MarketDataService`.

## File Dibuat

- `app/market/history.py` berisi `HistoricalMarketDataEngine`, `HistoryLoader`, dan `HistoryLoadResult`.
- `app/market/cache.py` berisi `HistoricalCandleCache` dengan TTL default 900 detik.
- `app/market/storage.py` berisi `SQLiteCandleStorage` untuk persist candle dan cache metadata.

## File Diintegrasikan

- `app/market/data_service.py` sekarang memanggil history loader sebelum fallback ke download langsung dan sample data.

## Behavior

- Jika cache valid dan jumlah candle cukup, `fetch_ohlcv` mengembalikan source `cache`.
- Jika cache tidak ada atau expired, engine mendownload OHLCV memakai jalur existing `MarketDataService`.
- Hasil download disimpan ke SQLite lalu dikembalikan sebagai source `download`.
- Jika history path gagal, service tetap menjaga backward compatibility dengan jalur ccxt, public HTTP, lalu sample data.

## Safety Boundary

- Tidak ada live trading.
- Tidak ada API key.
- Tidak ada order execution.
- Cache hanya menyimpan market candle publik.

## Verification

- `python -m compileall app`

## Sprint Berikutnya

Sprint 10 belum dimulai. Kandidat fokus berikutnya tetap batch backtest atau ranking artifact lanjutan setelah history engine stabil.