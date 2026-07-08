# Crypto Quant Bot

Starter project untuk platform trading crypto deterministik berbasis rule engine, JSON signal, risk management, paper trading, dan backtest.

Proyek ini sengaja belum melakukan live trading. Tahap awal dibuat aman: semua sinyal dihitung dari data contoh, lalu dibaca oleh paper broker. Live execution baru ditambahkan setelah rule, risk, dan backtest stabil.

## Cara menjalankan

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

Scan harga publik crypto:

```powershell
python scan_market.py
```

Command ini mencoba mengambil candle publik dari exchange yang diatur di `configs/market_scan.json`. Tahap ini tidak memakai API key, tidak membaca saldo, dan tidak membuat order. Kalau `ccxt` belum terpasang atau koneksi exchange gagal, scanner akan memakai data contoh agar alur scoring tetap bisa dites.

Urutan koneksi scanner:

1. Coba `ccxt` jika library sudah terpasang.
2. Jika `ccxt` belum ada, coba HTTP publik Binance/OKX bawaan Python.
3. Jika koneksi internet/exchange diblokir, pakai data contoh dan tampilkan `warning`.

Jalankan realtime scanner:

```powershell
python run_realtime.py
```

Realtime scanner akan scan berulang sesuai `configs/realtime.json`, menulis hasil terbaru ke `logs/latest_signals.json`, dan menyimpan riwayat ke `logs/signals.jsonl`.

Paper trading realtime aktif lewat `configs/paper_trading.json`. Ini hanya simulasi:

- saldo virtual disimpan di `logs/paper_state.json`
- riwayat event disimpan di `logs/paper_trades.jsonl`
- posisi hanya dibuka jika signal `BUY`
- posisi ditutup otomatis jika harga menyentuh stop loss atau take profit pertama

Panduan VPS ada di `DEPLOY_VPS.md`.

API internal:

```powershell
python run_api.py
```

Endpoint awal:

- `GET /health`
- `GET /status`
- `GET /signals/latest`
- `GET /paper/state`

Untuk live trading sungguhan, default proyek tetap terkunci:

- `configs/live_trading.json` berisi `enabled: false`
- `.env` harus berisi API key exchange
- `LIVE_TRADING_ENABLED=true` harus diaktifkan manual
- `LIVE_TRADING_DRY_RUN=false` harus diaktifkan manual

Jangan menyalakan live order sebelum paper trading terbukti stabil.

## Struktur utama

```text
app/
  market/       market data dan candle
  indicators/   indikator teknikal
  strategies/   strategi deterministic
  scoring/      rule engine berbobot
  signals/      JSON signal builder
  risk/         position sizing dan batas risiko
  paper/        simulasi order tanpa uang asli
  backtest/     runner backtest sederhana
  execution/    tempat live execution nanti
  exchange/     adapter exchange nanti
configs/
  rules.json    konfigurasi rule dan bobot
```

## Prinsip desain

- LLM tidak mengambil keputusan trading.
- Rule engine harus deterministic: input sama menghasilkan output sama.
- Semua keputusan keluar sebagai JSON signal.
- Execution engine hanya membaca signal, bukan berpikir sendiri.
- Machine learning nanti dipakai untuk optimasi bobot dari hasil backtest, bukan untuk klik buy/sell langsung.

## Referensi Vibe-Trading

Repo [HKUDS/Vibe-Trading](https://github.com/HKUDS/Vibe-Trading) bisa dipakai sebagai referensi tambahan untuk lapisan riset, data loader, backtest, report, dan workflow CLI/Web UI.

Yang kita ambil:

- Pola research workflow: plan, ground, execute, validate, deliver.
- Konsep data fallback untuk crypto melalui OKX/ccxt/local data.
- Konsep run artifact: hasil backtest harus bisa disimpan, dibaca ulang, dan diaudit.
- Konsep Shadow Account: membandingkan aturan ideal dengan eksekusi nyata.
- Konsep safety guard: live trading harus punya batas risiko, audit, dan kill switch.

Yang tidak kita ambil sebagai inti:

- LLM sebagai pengambil keputusan buy/sell.
- Auto live trading sebelum backtest dan paper trading stabil.
- Dependency besar sebagai syarat menjalankan bot dasar.

Jika ingin memakai Vibe-Trading sebagai alat riset opsional:

```powershell
pip install -r requirements-research.txt
vibe-trading init
vibe-trading run -p "Backtest a BTC-USDT 20/50 moving-average strategy for 2024 and summarize return and drawdown"
```

Bridge opsional tersedia di `app/research/vibe_trading_bridge.py`. Modul ini hanya membantu memanggil CLI Vibe-Trading untuk riset, bukan untuk mengeksekusi order.

## Langkah berikutnya

1. Tambahkan data real exchange via ccxt.
2. Lengkapi rule sampai 100+ rule.
3. Jalankan backtest banyak pair dan timeframe.
4. Tambahkan paper trading real-time.
5. Baru aktifkan live trading dengan API key read/write yang dibatasi.
