# Deploy ke VPS

Panduan ini menjalankan scanner realtime di VPS. Tahap ini masih aman: hanya membaca harga publik dan membuat signal JSON. Belum ada order live dan belum butuh API key.

## 1. Siapkan VPS

Pilih VPS Linux Ubuntu. Spesifikasi awal cukup kecil:

- 1 vCPU
- 1-2 GB RAM
- 20 GB storage

Login ke VPS lewat terminal:

```bash
ssh root@IP_VPS_KAMU
```

## 2. Install kebutuhan dasar

```bash
apt update
apt install -y python3 python3-venv python3-pip git
```

Kalau tersedia Python 3.13, itu paling sesuai dengan target awal proyek. Untuk tahap scanner ini, Python 3.11+ umumnya cukup.

## 3. Upload proyek ke VPS

Cara paling rapi nanti lewat GitHub. Kalau belum pakai GitHub, folder `crypto-quant-bot` bisa di-upload manual ke VPS.

Target folder di VPS:

```bash
/opt/crypto-quant-bot
```

Jika folder sudah ada di VPS:

```bash
cd /opt/crypto-quant-bot
```

## 4. Buat virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Jika install `ccxt` gagal atau belum diperlukan, scanner tetap punya jalur HTTP publik untuk Binance/OKX.

## 5. Tes sekali jalan

```bash
python run_realtime.py --once
```

Hasil terbaru akan ditulis ke:

```text
logs/latest_signals.json
logs/signals.jsonl
```

Kalau `data_source` berisi `public_http` atau `live`, artinya VPS berhasil membaca harga publik exchange.

Kalau `data_source` masih `sample`, lihat field `warning`. Biasanya penyebabnya koneksi exchange diblokir, DNS bermasalah, atau dependency belum terpasang.

## 6. Jalankan realtime manual

```bash
python run_realtime.py
```

Default scan setiap 60 detik. Ubah di:

```text
configs/realtime.json
```

Untuk menghentikan manual mode, tekan `Ctrl+C`.

## 7. Jalankan otomatis 24/7 dengan systemd

Copy service:

```bash
cp deploy/crypto-quant-bot.service /etc/systemd/system/crypto-quant-bot.service
systemctl daemon-reload
systemctl enable crypto-quant-bot
systemctl start crypto-quant-bot
```

Cek status:

```bash
systemctl status crypto-quant-bot
```

Lihat log realtime:

```bash
journalctl -u crypto-quant-bot -f
```

Restart bot:

```bash
systemctl restart crypto-quant-bot
```

Stop bot:

```bash
systemctl stop crypto-quant-bot
```

## 8. Realtime yang sebenarnya

Saat ini realtime berarti polling terjadwal, misalnya scan setiap 60 detik. Ini cukup untuk tahap awal rule engine, paper trading, dan backtest ringan.

Tahap berikutnya bisa dibuat lebih cepat:

- polling 5-10 detik untuk ticker
- candle 1m untuk strategi umum
- WebSocket untuk order book dan scalping
- Redis queue untuk memisahkan market data, scoring, dan execution

Jangan aktifkan live trading uang asli sebelum:

- backtest stabil
- paper trading stabil
- batas risiko jelas
- kill switch tersedia
- API key tidak punya izin withdrawal

## 9. Jalankan API internal

API ini untuk membaca status bot, signal terbaru, dan paper trading state. Default host adalah `127.0.0.1`, jadi tidak terbuka ke internet.

Tes manual:

```bash
python run_api.py
```

Jalankan 24/7:

```bash
cp deploy/crypto-quant-bot-api.service /etc/systemd/system/crypto-quant-bot-api.service
systemctl daemon-reload
systemctl enable crypto-quant-bot-api
systemctl start crypto-quant-bot-api
systemctl status crypto-quant-bot-api
```

Cek dari VPS:

```bash
curl http://127.0.0.1:8899/health
curl http://127.0.0.1:8899/status
```

Kalau ingin membuka API ke luar VPS, isi `BOT_API_KEY` di `/opt/crypto-quant-bot/.env`, ubah `BOT_API_HOST=0.0.0.0`, dan batasi firewall. Cara paling aman untuk awal adalah tetap pakai SSH tunnel, bukan expose publik.

## 10. API key exchange

Belum dibutuhkan untuk scanner, paper trading, dan API status.

Nanti saat siap cek akun exchange, buat API key dengan aturan:

- withdrawal harus OFF
- mulai read-only dulu
- setelah benar-benar siap, baru aktifkan trading permission
- batasi IP VPS jika exchange mendukung

Simpan di `/opt/crypto-quant-bot/.env`:

```bash
EXCHANGE_ID=binance
EXCHANGE_API_KEY=isi_api_key
EXCHANGE_SECRET=isi_secret
EXCHANGE_PASSWORD=
LIVE_TRADING_ENABLED=false
LIVE_TRADING_DRY_RUN=true
BOT_API_KEY=ganti_dengan_token_panjang
```

Cek koneksi akun:

```bash
source .venv/bin/activate
python check_exchange_api.py
```

Live order tetap tidak akan aktif selama `LIVE_TRADING_ENABLED=false` dan `configs/realtime.json` masih `live_execution_enabled: false`.

## 11. Deploy dengan Docker Compose

Alternatif systemd manual adalah Docker Compose:

```bash
cp .env.example .env
docker compose up -d --build
docker compose logs -f
```

Service API listen di `127.0.0.1:8899` dan realtime runner menulis artifact ke `logs/`. Untuk expose dashboard lewat domain, copy `deploy/nginx.conf` ke konfigurasi Nginx dan tetap set `BOT_API_KEY`.

## 12. Dashboard final

Dashboard read-only tersedia di:

```text
http://127.0.0.1:8899
```

Fitur utama: scanner, portfolio reconciliation, live orders, paper account, analytics, trade journal, WebSocket event stream, system health, dan responsive mobile navigation. Dashboard tidak menyediakan tombol BUY/SELL/Cancel.
