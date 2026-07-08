# Checkpoint Sprint 14

Status: completed.

Tanggal checkpoint: 2026-07-07.

## Goal

Sprint 14 menambahkan Binance Exchange Connector read-only sebagai official exchange interface awal untuk platform.

## Architecture Updates

- Menambahkan package modular `app/exchange/binance/` untuk Binance connector.
- `BinanceConnector` mengimplementasikan kontrak `ExchangeClient` existing melalui `fetch_candles` dan `fetch_ticker`.
- `MarketDataService` dapat memakai `BinanceConnector` secara transparan untuk exchange `binance` tanpa mengubah scanner.
- Historical cache tetap lewat `HistoryLoader` dan `HistoricalMarketDataEngine` yang sudah ada.
- Private endpoint menggunakan API key dari `.env` atau environment variable dan HMAC SHA256 signature.
- Connector read-only: hanya `GET`, tidak ada order execution, tidak ada BUY, SELL, cancel order, atau POST `/order`.

## Supported Endpoints

Public Spot REST API:

- `GET /api/v3/exchangeInfo`
- `GET /api/v3/ticker/price`
- `GET /api/v3/ticker/24hr`
- `GET /api/v3/depth`
- `GET /api/v3/klines`
- `GET /api/v3/ticker/bookTicker`

Private read-only Spot REST API:

- `GET /api/v3/account`
- `GET /api/v3/openOrders`
- `GET /api/v3/allOrders`
- `GET /api/v3/myTrades`

## Error Handling

- Network timeout melalui `BinanceNetworkTimeout`.
- HTTP error melalui `BinanceHTTPError`.
- Invalid API key/signature melalui `BinanceInvalidAPIKey`.
- Rate limit melalui `BinanceRateLimitError`.
- Invalid symbol melalui `BinanceInvalidSymbol`.
- Empty response melalui `BinanceEmptyResponse`.
- Invalid configuration melalui `BinanceConfigurationError`.

## Files Changed

- `app/exchange/binance/__init__.py`
- `app/exchange/binance/client.py`
- `app/exchange/binance/market.py`
- `app/exchange/binance/account.py`
- `app/exchange/binance/websocket.py`
- `app/exchange/binance/auth.py`
- `app/exchange/binance/signer.py`
- `app/exchange/binance/models.py`
- `app/exchange/binance/exceptions.py`
- `app/market/data_service.py`
- `configs/exchange.json`
- `.env.example`
- `docs/CHECKPOINT_SPRINT_14.md`

## Safety Boundary

- Tidak mengubah Scanner.
- Tidak mengubah Backtest.
- Tidak mengubah Rule Engine.
- Tidak mengubah Risk Engine.
- Tidak mengubah Portfolio.
- Tidak menambahkan order execution.
- Tidak memanggil `POST /order`.

## Verification

- `python -m compileall app`

## Known Limitations

- WebSocket masih placeholder read-only URL builder, belum streaming client aktif.
- Tidak menjalankan network smoke test agar tidak memanggil endpoint eksternal saat checkpoint.
- Private endpoint membutuhkan API key read-only Binance yang valid di `.env` atau environment variable.

## Sprint Berikutnya

Sprint 15 belum dimulai.