# Status Pengerjaan — Crypto Quant Bot

> Update file ini setiap selesai batch kerja (atau setiap merge ke `main`).  
> Tujuan: programmer berikutnya langsung tahu **sampai mana**, **apa yang aman disentuh**, dan **apa yang masih terbuka**.

**Terakhir di-update:** 2026-07-25  
**Branch utama:** `main`  
**Environment production:** `/opt/crypto-quant-bot` (VPS Linux)

---

## Ringkasan singkat

Bot quant deterministik (rule engine + paper/live path) dengan dashboard read-only.  
Scanner market terminal + ranking long/short dari Binance public API.  
Dashboard responsive: **desktop = tabel**, **mobile = kartu**.
Observability P0: `scan_stats` per siklus + agent entry filter counters.

---

## Yang sudah selesai (stabil)

### Scanner / market data
- Sumber data: **Binance spot public** (`ticker/24hr`, `exchangeInfo`, `klines`).
- Config: `configs/market_scan.json`
  - `exchange: binance`
  - `symbol_mode: momentum_liquid`
  - `prefilter_top_n: 100` → universe scan
  - `top_n: 20` → ranking final long/short (maksimal 20)
  - `min_quote_volume_usdt: 5_000_000`
  - `min_move_pct: 5.0`
- Prefilter `momentum_liquid` (2026-07-24):
  - Prioritas coin gerak ≥ `min_move_pct`
  - **Pad** sisa slot sampai `prefilter_top_n` dengan coin liquid volume tertinggi
  - Supaya ranking bisa penuh ke `top_n: 20` saat market sepi movers
- Output scan: `logs/latest_signals.json` (`signals`, `short_signals`, `market_breadth`, `move_alerts`, **`scan_stats`**)
- Pill dashboard `N long · N short` = `len(signals)` / `len(short_signals)` dari file itu (bukan hardcode UI)


### Observability (2026-07-25)
- `ScanRankings.scan_stats`: `prefilter_count`, `scanned_count`, `skipped_count`, `ranked_long/short`, `long/short_actionable`, `mode`, `exchange`, `timeframe`, `duration_ms`
- Ditulis ke `logs/latest_signals.json` via `write_scan_outputs(..., scan_stats=...)`
- Log baris `scan_stats mode=...` + ringkasan di loop `run_realtime`
- Agent bridge summary: `entry_filter_counts` (`low_confidence`, `failed_gates`, `action_*`, `evaluated`, cap), plus counters monitor
- Log baris `agent_pipeline in=... filters=...`
- Soft-entry WATCH: `allow_watch_soft_entry`, `min_watch_confidence`, `max_watch_soft_entry`

### Dashboard UI
- Desktop scanner: baris tabel + header Pair / Price / 24H / Vol / Liq / Status · Conf
- Mobile scanner: kartu (tidak diubah bentuk desktop)
- Mobile labels **Status** + **Reason** di atas badge/chip (style selaras Price/24H)
- Orders: tabel di desktop (`desktop-only`), kartu di mobile (`mobile-only`)
- CSS rule: **base = mobile card**; layout tabel **hanya** di `@media (min-width:641px)`  
  → jangan taruh style desktop di luar media query (bocor ke mobile)

### File UI penting
| File | Peran |
|------|--------|
| `app/dashboard/static/dashboard.css` | Layout desktop/mobile scanner + orders |
| `app/dashboard/templates/index.html` | Markup + render scanner rows |
| `app/dashboard/static/dashboard.js` | Orders cards, realtime helpers |
| `app/exchange/public_http_client.py` | Prefilter Binance ticker |
| `app/market/scanner.py` | Ranking long/short `top_n` + `scan_stats` |
| `app/agent_pipeline/bridge.py` | Agent filter/skip counters |
| `run_realtime.py` | Wire stats ke output + log siklus |
| `configs/market_scan.json` | Parameter scan |

---

## Yang perlu diketahui programmer baru

1. **Jangan otak-atik mobile layout** kecuali diminta. Desktop overrides hanya di `min-width:641px`.
2. **Jumlah coin di pill** ditentukan bot scan, bukan CSS. Cek `logs/latest_signals.json` dulu.
3. Setelah ubah prefilter/scanner: **restart bot realtime** agar proses lama tidak pakai kode lama.
4. Asset dashboard di-cache lewat `asset_version` (mtime CSS/JS) — hard refresh browser setelah deploy.
5. Python production: `./.venv/bin/python` (lihat `CLINE_RULES.md`).
6. Cek health scan: `scan_stats` di `latest_signals.json` atau `journalctl -u crypto-quant-bot -n 30`.
7. Cek kenapa agent `entries` sepi: lihat `logs/agent_pipeline.json` → `summary.entry_filter_counts`.

---

## Cara update status ini (workflow GitHub)

### Opsi A — paling sederhana (langsung di GitHub web)
1. Buka repo di GitHub → file `STATUS.md` (atau `README.md`)
2. Klik **pencil (Edit)**
3. Edit bagian **Terakhir di-update** + ringkasan batch kerja
4. **Commit changes** ke `main` (atau branch + Pull Request)

### Opsi B — dari VPS / lokal (disarankan)
```bash
cd /opt/crypto-quant-bot

# 1) Tulis status di STATUS.md (dan/atau CHANGELOG.md)
# 2) Lihat perubahan
git status
git diff

# 3) Commit dengan pesan jelas (bukan "Deskripsi perubahan")
git add STATUS.md README.md
git commit -m "docs: update STATUS after scanner prefilter pad + mobile labels"

# 4) Push ke GitHub
git push origin main
```

### Opsi C — Pull Request (tim / review)
```bash
git checkout -b docs/status-2026-07-24
# edit STATUS.md
git add STATUS.md
git commit -m "docs: status update 2026-07-24"
git push -u origin docs/status-2026-07-24
# buka PR di GitHub UI
```

### Tips pesan commit
Buruk: `Deskripsi perubahan`  
Baik:
- `docs: STATUS — scanner pad to top_n + UI mobile labels`
- `fix(scanner): pad momentum_liquid universe to prefilter_top_n`
- `fix(ui): desktop table Status/Conf; keep mobile cards`

---

## Template entry baru (copy-paste ke atas file ini)

```markdown
## [YYYY-MM-DD] — judul singkat
- **Siapa:** nama / agent
- **Apa:** 2–5 bullet hasil kerja
- **File utama:** path1, path2
- **Verifikasi:** pytest … / hard refresh dashboard / restart bot
- **Masih terbuka:** …
```

---

## Log batch terbaru

### [2026-07-25] — Soft-entry WATCH (agent P1)
- **Siapa:** agent
- **Apa:**
  - Soft-entry: top WATCH (conf ≥ `min_watch_confidence`, default 75) dievaluasi Chart/Decision
  - Hard BUY/SELL tetap prioritas; max soft slot `max_watch_soft_entry` (default 3)
  - Input agent menggabungkan raw scanner WATCH (ACR sering rewrite ke SKIP)
  - Counters: `watch_soft_evaluated`, `watch_low_confidence`, `max_watch_soft_entry_cap`
- **Config prod:** `allow_watch_soft_entry=true`, `min_watch_confidence=75`, `max_watch_soft_entry=3`
- **File utama:** `app/agent_pipeline/bridge.py`, `coordinator.py`, `run_realtime.py`, `configs/realtime.json`, tests
- **Verifikasi:** service active; log `watch_soft=N`; tests soft-entry + coordinator eligibility
- **Catatan:** Decision tetap bisa SKIP/HOLD — soft-entry ≠ auto buy

### [2026-07-25] — Observability screener + agent
- **Siapa:** agent
- **Apa:**
  - `scan_stats` di `ScanRankings` + `latest_signals.json`
  - Log ringkas scan per siklus (`prefilter/scanned/skipped/ranked/actionable/ms`)
  - Agent bridge: `entry_filter_counts` + summary monitor
  - Log ringkas agent di `run_realtime` main loop
- **File utama:** `app/market/scanner.py`, `app/agent_pipeline/bridge.py`, `run_realtime.py`, tests
- **Verifikasi:** pytest 16 passed; service restart; production log menunjukkan `scan_stats` + `agent_pipeline filters=...`
- **Temuan live:** ranking 20/20 OK; agent filter dominan `action_SKIP` (bukan crash). Confidence entry config prod `min_scanner_confidence=80`.

### [2026-07-24] — Dashboard desktop vs mobile + scanner universe
- Perbaiki desktop yang ikut layout mobile (base card + desktop media query)
- Desktop Status kiri / Conf kanan (isi kolom, tidak numpuk di ujung)
- Mobile: label Status + Reason (style metric labels); desktop label hidden
- Prefilter `momentum_liquid`: pad non-movers agar universe penuh → target top 20
- Tests: `tests/test_market_scanner.py` (8 passed)
- **Setelah deploy:** restart `run_realtime` / service bot, hard refresh dashboard
- **Catatan:** pill `13 long · 13 short` = hasil scan sebelum restart; setelah re-scan harus mendekati 20 jika scan sukses penuh

---

## Masih terbuka / follow-up
- [x] Restart bot production agar prefilter pad aktif; verifikasi pill ≈ `20 long · 20 short`
- [x] Log jumlah `scanned / skipped / ranked` per siklus di bot log
- [x] Soft-entry WATCH (top conf ≥ 75, max 3) lewat Chart/Decision
- [ ] (Opsional) Tuning `min_watch_confidence` / `max_watch_soft_entry` dari hasil paper 1–2 minggu
- [ ] (Opsional) Retry/backoff `PublicHttpExchangeClient._get_json`
- [ ] Rapikan commit message historis yang masih "Deskripsi perubahan" (opsional)
- [ ] README root masih campuran Windows PowerShell; production aktual Linux VPS
