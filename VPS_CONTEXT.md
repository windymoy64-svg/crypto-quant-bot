# VPS_CONTEXT — Crypto Quant Bot

> Info deployment di VPS.  
> **Jangan** menyimpan password, token, API key, private key, atau secret di file ini.

**Terakhir di-update:** 2026-07-26

---

## Ringkasan environment

| Item | Nilai |
|------|--------|
| OS target | Linux (Ubuntu-like) |
| Project path | `/opt/crypto-quant-bot` |
| Python | venv: `/opt/crypto-quant-bot/.venv` |
| User runtime | biasanya `root` atau user service (sesuaikan unit file) |
| Spesifikasi awal (panduan) | 1 vCPU, 1–2 GB RAM, ~20 GB disk |

---

## Path penting di server

```text
/opt/crypto-quant-bot/                 # root project
/opt/crypto-quant-bot/.venv/           # virtualenv
/opt/crypto-quant-bot/.env             # SECRET — jangan catat isinya di sini
/opt/crypto-quant-bot/configs/         # realtime, paper, market_scan, ...
/opt/crypto-quant-bot/logs/            # signals, paper_state, paper_trades, agent_pipeline
/opt/crypto-quant-bot/data/            # journal, observations, llm insights
/opt/crypto-quant-bot/deploy/          # unit systemd
```

### Log / state yang sering dicek
| Path | Isi |
|------|-----|
| `logs/latest_signals.json` | Hasil scan terbaru |
| `logs/signals.jsonl` | Riwayat signal |
| `logs/paper_state.json` | Saldo + open positions paper |
| `logs/paper_trades.jsonl` | Event open/partial/close |
| `logs/agent_pipeline.json` | Output coordinator terbaru |
| `data/llm_learning_insights.jsonl` | Insight LLM learning (bisa besar) |
| `data/learning_journal.jsonl` | Trade journal learning |

---

## Service yang digunakan

Unit file sumber ada di `deploy/`:

| Service (nama tipikal) | Peran | Entry |
|------------------------|-------|--------|
| `crypto-quant-bot` | Loop scanner + paper + agent | `run_realtime.py` |
| `crypto-quant-bot-api` | Dashboard / API internal | `run_api.py` |

Install (dari panduan deploy):

```bash
cp /opt/crypto-quant-bot/deploy/crypto-quant-bot.service /etc/systemd/system/
cp /opt/crypto-quant-bot/deploy/crypto-quant-bot-api.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable crypto-quant-bot crypto-quant-bot-api
systemctl start crypto-quant-bot crypto-quant-bot-api
```

> Jika proses dijalankan manual (`python run_realtime.py` / `run_api.py`) tanpa systemd, status `systemctl` bisa kosong — cek dengan `ps` / path venv.

### API listen (default aman)
- Host: `127.0.0.1` (bukan publik)  
- Port default: **8899** (override via env `BOT_API_PORT` di `.env` — **jangan tulis nilai secret**)  
- Auth: header/cookie API key bila `BOT_API_KEY` di-set  

Akses remote disarankan **SSH tunnel**, bukan buka `0.0.0.0` tanpa firewall.

---

## Command penting

### Aktivasi environment
```bash
cd /opt/crypto-quant-bot
source .venv/bin/activate
# atau panggil langsung:
# /opt/crypto-quant-bot/.venv/bin/python ...
```

### Tes sekali jalan (scanner/realtime)
```bash
cd /opt/crypto-quant-bot
.venv/bin/python run_realtime.py --once
```

### Jalankan manual (foreground)
```bash
.venv/bin/python run_realtime.py
.venv/bin/python run_api.py
```

### Systemd
```bash
systemctl status crypto-quant-bot
systemctl status crypto-quant-bot-api
systemctl restart crypto-quant-bot
systemctl restart crypto-quant-bot-api
systemctl stop crypto-quant-bot
journalctl -u crypto-quant-bot -n 50 --no-pager
journalctl -u crypto-quant-bot -f
journalctl -u crypto-quant-bot-api -n 50 --no-pager
```

### Health API (dari VPS, tanpa mencetak secret)
```bash
curl -sS http://127.0.0.1:8899/health
curl -sS http://127.0.0.1:8899/status
```
Endpoint terproteksi membutuhkan header Authorization Bearer — **jangan simpan key di file ini**.

### Tes
```bash
cd /opt/crypto-quant-bot
.venv/bin/python -m pytest tests/test_realtime_paper_engine.py -q
```

### Cek proses (tanpa secret)
```bash
ps -eo pid,rss,cmd | grep -E 'run_realtime|run_api' | grep -v grep
```

---

## Config yang sering disentuh (non-secret)

| File | Fungsi |
|------|--------|
| `configs/realtime.json` | Interval scan, paper path, agent_pipeline flags |
| `configs/paper_trading.json` | Paper enabled, risk_percent, max positions, paths |
| `configs/paper.json` | Paper batch + `min_risk_reward` (RiskManager path) |
| `configs/market_scan.json` | Universe / top_n / volume filter |
| `configs/live_trading.json` | Live default **disabled** |

---

## Operasi aman di VPS

1. **Jangan** `cat .env` atau paste secret ke chat / markdown.  
2. Sebelum `systemctl restart` / `kill` proses: jelaskan efek (downtime scan singkat, posisi paper tetap di state file).  
3. Jangan hapus `logs/paper_trades.jsonl` tanpa backup — audit trail.  
4. File insight/journal bisa **besar**; prefer `tail` / API slim, jangan load full ke editor.  
5. Live trading: hanya setelah checklist risk (lihat `DEPLOY_VPS.md` + `TASKS.md`).

---

## Referensi

- Panduan lengkap: `DEPLOY_VPS.md`  
- Todo / status kerja: `TASKS.md`  
- Arsitektur: `PROJECT_CONTEXT.md`  
- Aturan agent: `.clinerules`
