# TASKS — Crypto Quant Bot

> Update file ini setiap selesai batch kerja.  
> Tujuan: status operasional + antrian kerja tanpa menebak-nebak.

**Terakhir di-update:** 2026-08-08 (klarifikasi multi-exchange; tanpa perubahan kode)
**Environment:** `C:\Users\BIG MOUSE\Downloads\crypto-quant-bot-main` (Windows 10, Python 3.13; konteks produksi masih `/opt/crypto-quant-bot` VPS)

---

## Handoff sesi 2026-08-08 — Klarifikasi multi-exchange (Binance vs Bitunix)

### Jenis sesi
Tanya-jawab arsitektur; **tidak ada perubahan kode** yang dilakukan pada sesi ini.

### Ringkasan
- User bertanya kenapa live harus Binance padahal bisa Binance dan Bitunix.
- Diklarifikasi: **monitoring** sudah multi-exchange (credential per-exchange, view mode `multi`, agregasi data Binance+Bitunix), tetapi **eksekusi live** memakai satu `active_execution_exchange` (saat ini `binance`).
- Live Binance + Bitunix simultan belum didukung dengan aman; diperlukan `LiveExecutionRouter` (routing keputusan, sizing per venue, exposure aggregation, dedup idempotency, protective order per venue, rekonsiliasi, kill switch bersama) agar tidak menggandakan exposure.
- Keputusan fitur diserahkan ke user: lanjut aktivasi single-venue, atau bangun router multi-exchange.

### Pekerjaan belum selesai (masih berlaku dari sesi sebelumnya)
- Live belum aktif: persisted `mode=paper`, `live_confirmed=false`, exchange aktif `binance` tanpa credential tersimpan.
- Belum ada preflight network nyata, restart runner production, atau order live.
- Graphify belum di-update ulang setelah batch live/preflight/shared brain final.

### File dibuat/diubah/dihapus
- Tidak ada (sesi klarifikasi). File yang dibaca: `app/settings/exchange_credentials.py`, `app/settings/portfolio_preferences.py`, `app/dashboard/routes/settings.py`.

### Command penting
- Tidak ada command yang dijalankan.
- Status validasi terakhir dari sesi sebelumnya tetap berlaku: `python -m pytest` → **710 passed, 0 failed**; `compileall` OK; `node --check dashboard.js` OK.

### Error/kendala tersisa
- Tidak ada error baru. Blocker live aktual: credential belum tersimpan, persisted mode masih paper, belum ada preflight exchange nyata.

### Keputusan teknis
- Monitoring boleh multi-exchange; eksekusi live tetap single venue sampai router multi-exchange dibuat dan diuji.
- Tidak memaksakan live tanpa credential/preflight; fail-closed tetap dijaga.

### Status Graphify
- `graphify update` **tidak dijalankan** pada sesi ini (tidak ada perubahan kode).
- `graphify-out/graph.html`, `graphify-out/graph.json`, `graphify-out/GRAPH_REPORT.md` masih dari snapshot `2026-08-08` sebelumnya; belum mencerminkan batch final live/preflight.
- Graphify masih **BELUM** di-update ulang.

### Next Step
1. Keputusan user: (a) aktivasi live single venue — simpan credential via Settings, Test Connection/preflight (can_trade + saldo USDT), mode live + `ENABLE LIVE TRADING`, restart runner; atau (b) bangun dan tes `LiveExecutionRouter` untuk live multi-exchange.
2. Setelah keputusan, jalankan `graphify update .`.
3. Restart runner production hanya setelah preflight bersih dan persetujuan operasional.

---

## Handoff sesi 2026-08-08 — Final live readiness, shared brain, dan preflight

### Ringkasan pekerjaan selesai
- Audit keseluruhan dashboard dan sinkronisasi mode paper/dry-run/live dilakukan.
- Dashboard diperbaiki agar snapshot membawa `multi_portfolio` dan `execution_mode`.
- Analytics chart memilih sumber data berdasarkan execution mode.
- Status exchange dibedakan menjadi `connected`, `unavailable`, dan `not_configured`.
- Endpoint legacy `/health` diproteksi dengan `require_api_key`.
- Active Orders memiliki refresh Stop Loss/Trailing berdasarkan state posisi.
- Paper, dry-run, dan live memakai `AgentPipelineCoordinator` serta `ExecutorAgent` yang sama.
- Binance Futures live wiring ditambahkan melalui `FuturesHttpClient`, `FuturesOrderSubmissionEngine`, dan `BinanceFuturesExecutorAdapter`.
- Bitunix tetap memakai adapter live existing.
- Safety gate live tetap fail-closed; live tanpa adapter tidak fallback ke simulasi.
- Preflight live Binance diperbaiki agar memakai endpoint USD-M Futures, memeriksa `can_trade`, dan available USDT balance.
- `configs/realtime.json` diubah dari `live_execution_enabled: false` menjadi `true`.
- Test parity, adapter, dashboard source, trailing, dan preflight diperluas.

### Pekerjaan belum selesai
- Live belum diaktifkan secara operasional.
- Persisted execution preference masih `mode=paper`, `live_confirmed=false`.
- Credential exchange aktif belum terkonfigurasi pada workspace saat diverifikasi.
- Live multi-exchange Binance + Bitunix bersamaan belum didukung sebagai router aman; saat ini satu `active_execution_exchange` dipakai untuk eksekusi.
- Belum melakukan preflight network nyata, restart runner production, atau mengirim order live.
- Residual follow-up: token WebSocket di query, CDN pinning/SRI, nested Telegram/LLM HTML, dan label read-only pada Settings/Futures.

### File dibuat/diubah/dihapus
- **Diubah:** `configs/realtime.json`, `run_realtime.py`, `app/executor_agent/binance_futures_adapter.py`, `app/executor_agent/agent.py`, `app/agent_pipeline/bridge.py`, `app/dashboard/services.py`, `app/dashboard/app.py`, `app/dashboard/routes/multi_portfolio.py`, `app/dashboard/routes/settings.py`, `app/dashboard/static/dashboard.js`, `tests/test_realtime_runner.py`, `tests/test_dashboard_mode_source.py`, `tests/test_dashboard_orders_scroll.py`, `tests/test_dashboard_services.py`, `TASKS.md`, `SESSION_LOG.md`.
- **Dibuat:** tidak ada file baru pada batch final ini.
- **Dihapus:** tidak ada.
- Tidak ada secret, paper state, posisi, trade history, atau file runtime audit yang dihapus.

### Command penting
```powershell
python -m pytest tests/test_realtime_runner.py tests/test_executor_agent.py tests/test_agent_pipeline_bridge.py tests/test_binance_futures_adapter.py -q
# 48 passed

python -m pytest tests/test_settings_api.py tests/test_dashboard_futures_route.py tests/test_realtime_runner.py tests/test_binance_futures_account.py tests/test_binance_futures_adapter.py -q
# 44 passed

python -c "from app.settings.execution_preferences import load_execution_preferences; from app.settings.portfolio_preferences import load_portfolio_preferences; from app.settings.exchange_credentials import load_exchange_credentials; e=load_execution_preferences(); p=load_portfolio_preferences(); c=load_exchange_credentials(exchange=p.active_execution_exchange); print({'mode':e.mode,'live_confirmed':e.live_confirmed,'exchange':p.active_execution_exchange,'credentials_configured':bool(c and c.is_configured),'testnet':bool(c.testnet) if c else None})"
# mode=paper, live_confirmed=False, exchange=binance, credentials_configured=False

python -m compileall app tests
# OK

python -m pytest
# 710 passed, 0 failed

node --check app/dashboard/static/dashboard.js
# OK
```

### Error/kendala tersisa
- Runtime tidak dapat masuk live karena credential exchange belum tersedia dan persisted mode masih paper.
- `live_execution_enabled=true` pada file config bukan satu-satunya sumber kebenaran; `execution_preferences` tetap memerlukan mode live dan confirmation.
- Tanpa preflight exchange nyata, tidak dapat memastikan permission futures, saldo, endpoint testnet/mainnet, atau status service production.
- Warning runtime lama seperti Binance permission/API bootstrap dan TestClient/HTTPX tetap merupakan risiko operasional nonfatal; belum diverifikasi ulang terhadap environment production sesi ini.

### Keputusan teknis
- Execution brain tunggal dipertahankan untuk paper, dry-run, dan live.
- Perbedaan mode hanya pada adapter eksekusi.
- Live fail-closed jika credential, adapter, parity, safety gate, atau readiness tidak memenuhi syarat.
- `active_execution_exchange` tetap single venue untuk live; monitoring dapat multi-exchange.
- Tidak mengaktifkan live secara paksa dari database/config tanpa credential dan preflight.
- Withdrawal tetap OFF dan tidak ada order live yang dikirim pada sesi ini.

### Status Graphify
- `graphify update .` **sudah dijalankan** pada awal sesi setelah batch sinkronisasi dashboard.
- Pada perubahan live/preflight/shared brain setelah update tersebut, Graphify **belum di-update ulang**.
- `graph.html`, `graph.json`, dan `GRAPH_REPORT.md` berhasil diperbarui pada update sebelumnya, tetapi belum mencerminkan seluruh perubahan final live/preflight sesi ini.
- Graphify terakhir mencatat 5.668 nodes, 13.837 edges, dan 303 communities.

### Next Step
1. Simpan credential exchange melalui Settings tanpa mencetak secret.
2. Pilih satu `active_execution_exchange` untuk eksekusi live; gunakan mode multi hanya untuk monitoring.
3. Jalankan Test Connection/preflight pada exchange terpilih dan pastikan `can_trade=true`, available USDT > 0, serta testnet/mainnet benar.
4. Masukkan confirmation persis `ENABLE LIVE TRADING`, ubah persisted mode ke `live`, lalu verifikasi summary tanpa menampilkan secret.
5. Jalankan `graphify update .` untuk mencerminkan perubahan final sesi ini.
6. Restart runner production hanya setelah preflight bersih dan konfirmasi operasional; pantau protective SL/TP order pertama.

---

## Handoff sesi 2026-08-08 — Live config ON dan Futures preflight

### Sudah dikerjakan
- `configs/realtime.json` sekarang menetapkan `live_execution_enabled: true`.
- Settings live tidak lagi menolak Binance secara hardcoded.
- Preflight live Binance sekarang memakai USD-M Futures `/fapi/v3/account`, bukan Spot `/api/v3/account`.
- Preflight memvalidasi credential, `can_trade`, dan available USDT balance.
- Preflight Bitunix tetap memakai endpoint Bitunix existing.

### Verifikasi
```powershell
python -m pytest
# 710 passed, 0 failed

python -m compileall app tests
# OK

node --check app/dashboard/static/dashboard.js
# OK
```

### Status runtime aktual
- File config: live execution **ON**.
- Persisted execution mode: **paper**.
- Live confirmation: **false**.
- Active exchange: **binance**.
- Binance credentials: **belum terkonfigurasi**.
- Tidak ada koneksi exchange nyata atau order live yang dijalankan.

### Next step
- Simpan credential Binance Futures melalui Settings tanpa mencetak secret, pilih testnet/mainnet dengan sadar, jalankan Test Connection, lalu konfirmasi live phrase sebelum mengubah persisted mode menjadi live.

---

## Handoff sesi 2026-08-08 — Shared trading brain dan live exchange wiring

### Sudah dikerjakan
- Paper, dry-run, dan live tetap melewati `AgentPipelineCoordinator` serta `ExecutorAgent` yang sama; perbedaan mode hanya pada adapter eksekusi.
- Binance Futures kini memiliki wiring `FuturesHttpClient` -> `FuturesOrderSubmissionEngine` -> `BinanceFuturesExecutorAdapter`.
- Safety gate live tetap wajib: enabled, bukan dry-run, dan konfirmasi live.
- Live tanpa adapter tidak pernah fallback menjadi simulasi; order ditolak fail-closed.
- Pipeline melaporkan `live_blocker` jika parity atau readiness belum terpenuhi.
- Binance account balance adapter ditambahkan untuk sizing runtime live.
- Test parity dan adapter ditambahkan.

### Final verification
```powershell
python -m pytest
# 710 passed, 0 failed

python -m compileall app tests
# OK

node --check app/dashboard/static/dashboard.js
# OK
```

### Status live aktual
- Live **belum dinyalakan secara operasional** dari workspace ini.
- Tidak ada credential yang dicetak atau dikirim.
- Tidak ada service production yang direstart.
- Tidak ada order live yang dikirim.
- Untuk aktivasi nyata, perlu preflight credential exchange, permission futures, saldo USDT, testnet/mainnet target, dan restart runner yang disetujui.

### Next step
- Jalankan preflight koneksi exchange pada environment target, lalu aktifkan live hanya setelah hasil koneksi dan permission diverifikasi.

---

## Handoff sesi 2026-08-08 — Audit keseluruhan dan sinkronisasi dashboard

### Sudah dikerjakan
- Snapshot dashboard sekarang membawa `multi_portfolio` dan `execution_mode` serta tetap mempertahankan payload paper/live yang ada.
- Analytics Apex chart memilih sumber berdasarkan execution mode; mode non-paper memakai `multiPortfolio`.
- Status multi-portfolio membedakan data exchange `connected`, `unavailable`, dan `not_configured`.
- Endpoint legacy `/health` sekarang mengikuti proteksi `require_api_key`.
- Active Orders memiliki refresh metadata Stop Loss/Trailing per detik tanpa rebuild tabel, sehingga level trailing mengikuti state posisi terbaru.
- Ditambahkan behavioral assertions untuk sumber analytics, snapshot mode, trailing target, dan proteksi health.

### Final verification
```powershell
python -m pytest
# 708 passed, 0 failed

python -m compileall app tests
# OK

node --check app/dashboard/static/dashboard.js
# OK
```

### Residual risk
- Selector `render()` lama masih berupa fungsi JavaScript satu-baris dan belum direfactor menjadi helper tunggal; jalur HTTP utama sudah memuat execution mode sebelum data.
- Token WebSocket di meta/query, CDN tanpa SRI/pinning, nested Telegram panel, dan label read-only Settings/Futures masih menjadi follow-up terpisah.
- Tidak ada restart service atau perubahan live/paper state pada batch ini.

### Next step
- Hard refresh dashboard, kemudian audit visual mode paper/dry-run/live dan status `exchange unavailable`.

---

## Handoff sesi 2026-08-08 — Orders trailing/reason history

### Sudah dikerjakan
- Payload paper Order History sekarang meneruskan `reason`, `close_reason`, dan `close_label`.
- Normalisasi frontend memprioritaskan `close_label`, lalu `reason`, lalu `close_reason`.
- Active Orders memberi ID stabil pada elemen Stop Loss dan Trailing sehingga nilai snapshot engine dapat ditampilkan tanpa rebuild shell tabel.
- Helper `patchActiveOrderStops()` ditambahkan untuk memperbarui level Stop Loss/Trailing ketika posisi dirender ulang.
- Test regresi reason dan target trailing ditambahkan.

### Validasi
```powershell
python -m pytest tests/test_dashboard_services.py tests/test_dashboard_orders_scroll.py -q
# 18 passed

python -m compileall app tests
# OK

node --check app/dashboard/static/dashboard.js
# OK

python -m pytest
# 706 passed, 0 failed
```

### Catatan
- Backend trailing engine tetap authoritative; panel membaca `trailing_stop_loss`, `trailing_active`, dan `stop_loss` dari posisi.
- Tidak ada restart service, perubahan paper state, history trading, atau live flag.
- Live tetap OFF. Dashboard perlu hard refresh untuk memuat static JS terbaru.

### Next step
- Verifikasi visual menu Orders setelah hard refresh pada posisi paper yang trailing-nya aktif.

---

## Handoff sesi 2026-08-08 — Perbaikan test mode source + final verification

### Sudah dikerjakan
1. Memperketat kontrak sumber dashboard agar mode persisted menjadi authoritative:
   - Panel dashboard memilih data real untuk mode non-paper tanpa fallback berdasarkan `accounts_connected`.
   - Monitor posisi live memilih sumber berdasarkan `state.executionMode`.
   - Panel tambahan (`__livePanelSource`) memilih paper/real berdasarkan `window.__executionMode`.
2. Memperbarui `tests/test_dashboard_mode_source.py` dengan assertion regresi untuk mencegah fallback berbasis koneksi kembali.
3. Graphify di-update incremental setelah perubahan sesi sebelumnya.

### File dibuat/diubah pada batch ini
- `app/dashboard/static/dashboard.js`
- `app/dashboard/templates/index.html`
- `tests/test_dashboard_mode_source.py`
- `TASKS.md`
- `SESSION_LOG.md`

### Final verification
```powershell
python -m pytest tests/test_dashboard_mode_source.py tests/test_dashboard_orders_scroll.py -q
# 18 passed

python -m compileall app tests
# OK

node --check app/dashboard/static/dashboard.js
# OK

python -m pytest
# 704 passed, 0 failed
```

### Risiko/dependency
- Tidak ada perubahan pada paper state, trade history, live flag, atau service runtime.
- Live tetap OFF.
- Dashboard static memerlukan hard refresh browser.
- Warning runtime TestClient/HTTPX dan bootstrap Binance `-2015` tetap nonfatal dan tidak memblokir test suite.

### Next step
- Berhenti setelah final verification; tidak memulai sprint baru otomatis.

---

## Handoff sesi 2026-08-08 — Audit + perbaikan sinkronisasi menyeluruh, lalu 704/704 test hijau

### Konteks
Batch kerja: "check semua fitur/menu; perbaiki yang belum sinkron" → audit read-only semua fitur (live mode, Settings: **LLM / Telegram / Trading Defaults**, AI agents, menu **Agents**, dashboard), lalu perbaikan menyeluruh dan penuntasan seluruh test suite hingga **704 passed / 0 failed**.

### Sudah dikerjakan di sesi ini
1. **Dashboard ↔ execution mode (autoritatif):**
   - `loadAll()` di `dashboard.js` memuat `/api/settings/execution` dulu; `state.executionMode` sebagai satunya penentu paper vs real.
   - `render()` dan panel tidak lagi memilih sumber pakai heuristik `accounts_connected`; `syncDashboardPanels()` memanggil semua renderer (market, portfolio, live orders, dll).
   - Websocket snapshot: panggil `render()` + `syncDashboardPanels()` + `syncLivePanels()` terkontrol (delay 800ms), fallback live hanya saat tidak ada data real.
   - `handleError()` tidak lagi mereset ke `clone(DEFAULT_PAYLOAD)` yang menampilkan harga sintetis; tetap pakai `state.lastPayload`.
2. **Settings — Telegram / LLM / Trading Defaults:**
   - Kredensial Telegram dibaca dari settings store (`_telegram_credentials()`), disable Telegram tidak lagi menghapus token, `load_telegram_credentials()` tersedia (env hanya bootstrap).
   - Test LLM & Telegram memakai field timeout/result dari store; hasil test tampil ke UI (`telegram-test-result`).
   - Trading Defaults (TP/3%, SL%, trailing, leverage, modal dimainkan, RR) diteruskan ke `ExecutorAgent` (param `take_profit_percent`, `stop_loss_percent`, `trailing_stop_percent`) dan dipakai menghitung stop/tp1 pada posisi baru.
3. **Runtime & scheduler:**
   - `scheduler.py`: `misfire_grace_time=300`, `coalesce=True`, `max_instances=1`.
   - `run_realtime.py`: telegram memakai store, `_telegram_event_sent_at` benar, release memory tanpa `TypeError`.
4. **Office/Agents:**
   - `_live_trading_flags()` di `app/dashboard/office/state.py` dibaca dari persisted `load_execution_preferences()`; Dami mengikuti mode persisted (paper/dry_run/live).
   - TradeRepublic Telegram: `TradeReporter.format_live_execution()` + `notify_live_pipeline_executions()` untuk notifikasi eksekusi live.
5. **Data integrity:** `app/data/` baru (`data_integrity.py`) dengan garansi ambang waktu `+5s`; `tests/__init__.py` baru.
6. **Scoring & multi-timeframe (final fixes):**
   - `calculate_rsi_score`: range 65–78 → 70.
   - `calculate_ema_score`: komponen independen (price>ema20=30, ema20>ema50=20, all-aligned+25) → perfect=75.
   - Default netral 50 untuk volatility/liquidity/relative_strength ketika data sinyal tidak menyediakan.
   - Gate SKIP hanya jika `failed_gates>2 && total<75`.
   - Multi-timeframe: skor terpisah per trend (BULLISH/BEARISH/NEUTRAL); gate keras hanya pada timeframe `1d` (timeframe pendek = warning).
7. **Test suite hijau.** 704/704, termasuk kontrak baru `test_dashboard_mode_source.py` (paper vs live).

### File dibuat/diubah pada sesi ini
- **Diubah:**
  - `app/scoring/scorer.py`
  - `app/strategies/multi_timeframe.py`
  - `app/dashboard/static/dashboard.js`
  - `app/dashboard/templates/index.html`
  - `app/dashboard/routes/settings.py`
  - `app/settings/telegram_preferences.py`
  - `app/executor_agent/agent.py`
  - `app/dashboard/office/state.py`
  - `app/dashboard/scheduler.py`
  - `run_realtime.py`
  - `app/telegram/trade_reporter.py`
  - `tests/test_dashboard_orders_scroll.py` (kontrak assertion disesuaikan ke execution-mode)
  - `TASKS.md` · `SESSION_LOG.md`
- **Dibuat:**
  - `app/data/__init__.py`
  - `app/data/data_integrity.py`
  - `tests/__init__.py`

### Command penting dan hasil
```powershell
python -m compileall app tests                # OK, tidak ada syntax error
python -m pytest tests/test_scorer.py tests/test_multi_timeframe.py -q   # 13 passed
python -m pytest tests/test_dashboard_mode_source.py -q                    # 4 passed
python -m pytest -q                            # 704 passed, 0 failed (full suite)
node --check app/dashboard/static/dashboard.js # OK
```

### Error atau masalah terakhir
- Tidak ada test yang gagal (704/704).
- Satu konflik assertion antar test selesai dengan mengubah test lama `test_dashboard_orders_scroll.py` (assert `realSourceSelected=realConnected||...` dihapus → diganti `const realSourceSelected=!paperMode`) karena sumber data kini ditentukan execution mode, bukan koneksi.
- Warning nonfatal TestClient/HTTPX & bootstrap Binance `-2015` masih ada dari runtime lama; live tetap OFF.

### Keputusan teknis
- **Execution mode adalah satu-satunya sumber kebenaran** panel dashboard (paper vs live), bukan koneksi/accounts.
- Kategori scoring tanpa data memakai baseline netral (50) agar tidak merusak skor total & gate.
- Gate keras strategy hanya timeframe `1d` (regime utama); TF dipendi jadi warning.
- Sesi ini tidak mengaktifkan live trading; tidak menyentuh config `live_enabled`, paper state, posisi, history.

### Next step chat baru
1. Jalankan `graphify` update untuk me-refresh knowledge graph setelah perubahan sesi ini (lihat status graphify di bawah).
2. Hard refresh dashboard; cek visual mode paper/live, Settings (LLM test, Telegram test, Trading Defaults), menu Agents.
3. Jalankan runtime lokal (mis. `python run_realtime.py`) dan verifikasi logs: telegram notify, executor stop/TP, status agents.
4. Lanjut pengujian end-to-end live/dry-run bila diminta; tidak ada sprint baru otomatis setelah ini.

---

## Handoff sesi 2026-07-30 — Handoff sebelum pindah chat

### Sudah dikerjakan di sesi ini
- Menjelaskan perbedaan operasional **Target TP (%)**, **Stop Loss (%)**, **Trailing Stop (%)**, **Target RR**, leverage, dan Modal dimainkan (%), termasuk hubungan Entry–SL–1R–TP serta perilaku HOLD/trailing/partial close.
- Menetapkan rekomendasi awal: Target RR `2`, leverage `5x`, field TP/SL/Trailing/Modal dimainkan dikosongkan untuk baseline; pengujian sizing margin dilakukan terpisah setelah RR stabil.
- Membuat mode exit saling eksklusif:
  - Target RR diisi → Target TP (%) dan Stop Loss (%) disabled.
  - Target TP (%) atau Stop Loss (%) diisi → Target RR disabled.
  - Mengosongkan nilai mengaktifkan kembali mode lawan.
- Menambahkan validasi API agar `target_risk_reward` tidak dapat disimpan bersama `take_profit_percent` atau `stop_loss_percent`.
- Menjaga Trailing Stop (%), Leverage, dan Modal dimainkan (%) tetap independen.
- Menambahkan hint dinamis yang menjelaskan mode aktif dan sumber SL saat Target RR digunakan.
- Menambahkan pembeda visual: mode aktif hijau; kolom disabled abu-abu redup dengan cursor `not-allowed`; kondisi semua kosong tetap netral.
- Tidak mengubah engine realtime, posisi paper aktif, paper state, trade history, atau live flag.

### File dibuat/diubah pada sesi ini
- **Dibuat:** tidak ada file baru.
- **Diubah:**
  - `/opt/crypto-quant-bot/app/dashboard/routes/settings.py`
  - `/opt/crypto-quant-bot/app/dashboard/static/dashboard.js`
  - `/opt/crypto-quant-bot/app/dashboard/static/dashboard.css`
  - `/opt/crypto-quant-bot/app/dashboard/templates/index.html`
  - `/opt/crypto-quant-bot/tests/test_settings_api.py`
  - `/opt/crypto-quant-bot/tests/test_settings_ui.py`
  - `/opt/crypto-quant-bot/TASKS.md`
  - `/opt/crypto-quant-bot/SESSION_LOG.md`
- Perubahan fixed-margin/Target RR dari handoff sebelumnya tetap berada di working tree dan tidak dioverwrite.

### Command penting dan hasil
```bash
.venv/bin/python -m pytest tests/test_settings_api.py -q --tb=short
# 14 passed, 1 warning deprecation nonfatal

.venv/bin/python -m pytest tests/test_settings_ui.py -q --tb=short
# 11 passed

.venv/bin/python -m pytest \
  tests/test_settings_api.py::test_trading_settings_reject_rr_with_manual_tp_or_sl \
  tests/test_settings_ui.py::test_tp_sl_and_target_rr_are_mutually_exclusive_in_ui -q --tb=short
# 3 passed, 1 warning deprecation nonfatal

node --check /opt/crypto-quant-bot/app/dashboard/static/dashboard.js
# OK

python -m py_compile /opt/crypto-quant-bot/app/dashboard/routes/settings.py
# OK

git -C /opt/crypto-quant-bot diff --check
# OK
```
- API direstart setelah perubahan route/UI: beberapa PID berubah selama operasi; status akhir `crypto-quant-bot.service` PID `9102` dan `crypto-quant-bot-api.service` PID `9107`, keduanya `active/running`.
- Realtime tidak perlu direstart karena engine Python tidak berubah pada batch eksklusivitas/warna; jika service otomatis berganti PID, tetap diverifikasi active/running.
- Konfigurasi akhir terverifikasi: `paper_enabled=True`, `live_enabled=False`.

### Error atau masalah terakhir
- Tidak ada assertion failure atau syntax error pada validasi terakhir.
- Beberapa command `git status`/output shell sempat timeout atau tidak tertangkap oleh environment, tetapi command tetap diverifikasi ulang secara sempit; `git diff --check` bersih.
- Warning nonfatal: `StarletteDeprecationWarning` dari integrasi `httpx`/TestClient.
- Warning runtime lama tetap ada saat bootstrap Binance Futures terkait permission/API key (`-2015`); tidak mengaktifkan live order dan tidak mengubah mode paper.
- Browser masih membutuhkan hard refresh agar asset CSS/JS terbaru terlihat.

### Keputusan teknis
- Target RR dan TP/SL manual diperlakukan sebagai dua mode exit yang mutually exclusive, bukan dua sumber TP yang boleh aktif bersamaan.
- Jika Target RR aktif, SL memakai signal/struktur; Target RR membentuk ladder TP berbasis Entry–SL.
- Jika TP atau SL manual aktif, Target RR harus kosong; API fail-closed untuk payload ambigu.
- Trailing Stop tetap independen karena merupakan mekanisme exit dinamis, bukan mode penentuan TP/SL awal.
- Perubahan hanya berlaku untuk posisi baru; posisi lama, state, dan audit history tidak dimigrasi.
- Live tetap OFF.

### Next step chat baru
1. Hard refresh dashboard dan cek warna/hint/disabled state pada panel Trading Defaults.
2. Verifikasi tiga kondisi UI: semua kosong; Target RR diisi; TP atau SL diisi.
3. Verifikasi GET/PUT Settings per exchange tidak menyimpan kombinasi Target RR + TP/SL.
4. Jika baseline RR ingin diuji, gunakan Target RR `2`, leverage `5x`, TP/SL/Trailing/Modal dimainkan kosong.
5. Setelah posisi baru tersedia, audit metadata `rr_tp1`, `tp_level_source`, SL final, dan geometry; jangan rewrite posisi lama.
6. Lanjutkan evaluasi partial TP (fraksi saat ini diterapkan terhadap remaining size), integrasi HOLD/trailing/`close_from_decision`, dan safety gate fixed-margin sebelum jalur live.

---

## Handoff sesi 2026-07-30 — Modal dimainkan (%), Target RR, leverage-aware sizing

### Sudah dikerjakan di sesi ini
- Mengaudit perhitungan futures dan runtime paper aktif: mode paper, live/network OFF, Settings Binance leverage 5x. Menjelaskan perbedaan quantity, notional, margin, risiko ke SL, PnL nominal, dan ROE dengan contoh runtime `SPCXB/USDT` serta `XRP/USDT`.
- Menambahkan dua Trading Defaults opsional dan per-exchange:
  - `target_margin_percent` / UI **Modal dimainkan (%)**;
  - `target_risk_reward` / UI **Target RR**.
- Jika Modal dimainkan diisi, posisi paper baru memakai fixed-margin sizing:
  - `target_margin = available_balance × target_margin_percent / 100`;
  - `target_notional = target_margin × leverage`;
  - `quantity = target_notional / entry`.
- Jika Target RR diisi, TP baru dibentuk dari jarak Entry–SL: TP1 = `RR`, TP2 = `RR+1`, TP3 = `RR+2`; position menyimpan `tp_level_source="configured_rr"`.
- Jika input kosong, perilaku lama dipertahankan: risk-based sizing (`risk_percent` + cap posisi) dan hybrid structural/minimum 2R.
- Menambah metadata audit posisi baru: `configured_margin_percent`, `configured_risk_reward`, dan `sizing_source` (`configured_margin` atau `default_risk`). Posisi/state/history lama tidak di-rewrite.
- Memverifikasi sinkronisasi dengan lifecycle posisi:
  - HOLD tetap bisa melewati seluruh fixed TP ladder dan memakai breakeven/trailing/agent EXIT;
  - non-HOLD tetap partial close dengan konfigurasi `tp_fractions` saat ini;
  - setelah partial close, `remaining_size` dan `used_capital` dihitung ulang leverage-aware;
  - trailing ATR/ACR atau override trailing percent tetap berjalan;
  - EXIT agent tetap memakai PnL ratio dalam satuan R dari Entry–SL dan remaining quantity.
- Tidak me-restart service, tidak mengubah preference aktif, tidak mengaktifkan live, dan tidak mengubah active orders.

### File dibuat/diubah pada sesi ini
- **Dibuat:** tidak ada file baru.
- **Diubah:**
  - `app/settings/trading_preferences.py`
  - `app/dashboard/routes/settings.py`
  - `app/dashboard/templates/index.html`
  - `app/dashboard/static/dashboard.js`
  - `app/paper/realtime_engine.py`
  - `run_realtime.py`
  - `tests/test_trading_preferences.py`
  - `tests/test_settings_api.py`
  - `tests/test_realtime_paper_engine.py`
  - `TASKS.md`
  - `SESSION_LOG.md`
- Working tree sudah berisi perubahan dari sesi lama; review diff/status sebelum commit dan jangan overwrite file yang bukan bagian batch ini.

### Command penting dan hasil
```bash
.venv/bin/python -m pytest \
  tests/test_realtime_paper_engine.py::test_configured_margin_and_rr_override_default_sizing \
  tests/test_realtime_paper_engine.py::test_percent_overrides_apply_to_new_long_position -q --tb=short
# 2 passed

.venv/bin/python -m pytest tests/test_trading_preferences.py -q --tb=short
# 3 passed

.venv/bin/python -m pytest \
  tests/test_settings_api.py::test_trading_settings_are_isolated_per_exchange \
  tests/test_settings_api.py::test_trading_settings_blank_values_restore_defaults \
  tests/test_settings_api.py::test_trading_settings_reject_invalid_percent_and_leverage -q --tb=short
# 3 passed, 1 deprecation warning nonfatal

.venv/bin/python -m pytest tests/test_realtime_paper_engine.py -q --tb=short
# 24 passed

.venv/bin/python -m pytest tests/test_acr_position_manager.py -q --tb=short
# 11 passed

.venv/bin/python -m py_compile app/settings/trading_preferences.py \
  app/dashboard/routes/settings.py app/paper/realtime_engine.py run_realtime.py
# OK

node --check app/dashboard/static/dashboard.js
# OK
```

### Error/masalah terakhir
- Service realtime dan API sudah direstart pada 2026-07-30 18:48–18:49 WIB; kode baru sudah dimuat. Fitur fixed-margin/Target RR berlaku untuk posisi baru setelah user menyimpan input Settings; posisi lama tidak dimigrasi.
- Input **Modal dimainkan (%) adalah margin allocation**, bukan persentase yang pasti hilang saat SL. Contoh available `$100`, modal 5%, leverage 25x, entry 100, SL 98: margin `$5`, notional `$125`, quantity `1.25`, tetapi loss di SL `$2.50`; RR 1:2 memberi gross profit `$5` bila 100% close di TP1.
- Saat TP biasa, konfigurasi `tp_fractions=(0.3, 0.3, 0.4)` diterapkan terhadap remaining quantity pada tiap tahap; hasil efektif dari size awal bukan persis 30/30/40. Ini perilaku lama dan belum diubah pada sesi ini; review bila user menginginkan fraksi absolut dari initial size.
- Target RR override tidak memaksa close ketika HOLD aktif; ini disengaja agar trend-hold tetap authoritative.
- Fetch dokumentasi resmi terhalang Binance JS/anti-bot dan Bitunix HTTP 403; tidak ada kutipan langsung palsu. Rumus diverifikasi terhadap model linear futures dan implementasi lokal.
- Beberapa command shell luas/status/diff timeout atau output tidak tertangkap; gunakan command sempit. Test terarah dan syntax check tetap hijau.
- Konteks lama menyebut `risk_percent=1.0`, tetapi file aktual yang diaudit sesi ini menunjukkan `configs/paper_trading.json` bernilai `0.5`; jangan mengandalkan handoff lama tanpa cek file/runtime aktual.

### Keputusan teknis
- Override modal eksplisit bersifat authoritative untuk sizing posisi paper baru; jika kosong, default risk sizing tetap dipakai penuh.
- `target_margin_percent` tervalidasi `(0, 100]`; `target_risk_reward` tervalidasi `(0, 100]`; keduanya opsional dan tersimpan per exchange.
- Leverage dipakai satu kali untuk mengubah margin target menjadi notional; PnL tetap `(price-entry) × quantity`, tidak dikali leverage lagi.
- RR mengatur geometri target relatif terhadap SL, bukan nominal profit akun. Nominal loss/profit tetap bergantung pada quantity dan jarak harga.
- HOLD/EXIT/trailing tetap authoritative setelah entry; field baru hanya menentukan initial sizing dan planned TP ladder.
- Semua perubahan forward-looking; active orders dan history lama tidak dimigrasi.
- Tetap low-resource: test terarah, tanpa full log JSONL, tanpa restart/test suite besar yang tidak perlu.

### Next step chat baru
1. Hard refresh dashboard agar asset Settings terbaru dimuat browser.
2. Simpan nilai **Modal dimainkan (%)** / **Target RR** yang diinginkan; semantics modal adalah margin allocation, bukan fixed loss di SL.
3. Verifikasi posisi baru menyimpan `configured_margin_percent`, `configured_risk_reward`, `sizing_source="configured_margin"`, dan `tp_level_source="configured_rr"`; jangan rewrite posisi lama.
4. Perbaiki/konfirmasi perilaku partial TP: saat ini 30% lalu 30% dari remaining lalu full pada target terakhir. Jika requirement adalah tepat 30%/30%/40% dari initial quantity, ubah dengan tes backward compatibility.
5. Tambahkan tes integrasi eksplisit fixed-margin + configured RR untuk HOLD, partial TP, trailing, dan `close_from_decision` dalam satu lifecycle.
6. Pertimbangkan safety gate tambahan (max account risk/liquidation buffer) untuk fixed-margin leverage tinggi sebelum jalur live digunakan.

### Batch terbaru — eksklusivitas mode TP/SL dan Target RR
- UI sekarang menonaktifkan TP + SL saat Target RR diisi.
- UI menonaktifkan Target RR jika TP atau SL manual diisi.
- API menolak konfigurasi ambigu yang mengisi Target RR bersamaan dengan TP/SL.
- Trailing Stop, leverage, dan Modal dimainkan tetap independen.
- API direstart; realtime tidak direstart karena tidak ada perubahan engine.
- Validasi: `tests/test_settings_api.py` 14 passed; `tests/test_settings_ui.py` 11 passed; JavaScript syntax check OK.
- Visual mode diperjelas: kolom aktif berwarna hijau; kolom disabled abu-abu redup dengan cursor `not-allowed`.

---

## Handoff sesi 2026-07-29 — Agent conflict, margin/ROE UI, paper risk 1%

### Sudah dikerjakan di sesi ini
- Menelusuri tiga Entry Candidates (`ETH/USDT`, `SPCXB/USDT`, `XLM/USDT`) yang decision-nya `-`: scanner memberi `BUY`, Chart Agent membaca `BEARISH`, dan policy `scanner_chart_conflict_policy=REJECT` menghentikan pipeline sebelum Decision Agent sehingga `decision=null` memang disengaja/fail-closed.
- Memperjelas UI Entry Candidates untuk conflict: tampil `REJECT`, score/regime fallback dari `chart_reading`, serta reason manusiawi dengan detail `scanner BUY vs chart BEARISH`; logic trading tidak diubah.
- Mengaudit FIL/USDT di Active Orders. `$149.46` adalah notional awal (`entry × size`), bukan modal. Dengan leverage 50x margin awal `$2.99`; setelah TP1 partial, remaining margin runtime `$2.09`.
- Memperbaiki Active Orders agar Modal memakai `used_capital` atau fallback `notional / leverage`, quantity memakai `remaining_size`, dan persentase PnL konsisten sebagai ROE terhadap margin.
- Memperbaiki bug PnL% yang meloncat sekitar faktor leverage: snapshot sudah memakai margin tetapi `price_update` masih memakai notional; kedua jalur kini memakai `positionMargin(...)` yang sama.
- Mempelajari formula futures linear Binance/Bitunix: notional = entry × quantity, initial margin = notional / leverage, PnL arah-aware, ROE = PnL / margin. Halaman resmi memblokir fetch otomatis (Binance anti-bot/JS; Bitunix HTTP 403), sehingga tidak membuat klaim kutipan yang tidak berhasil dibaca.
- Menyamakan Home/Overview **Real-Time P&L Stream** dengan Active Orders: persentase sekarang ROE terhadap `used_capital`, fallback `notional / leverage`, bukan perubahan harga coin.
- Menjelaskan sizing: `risk_percent` adalah batas rugi ke SL; `max_position_size_percent` adalah batas maksimum margin, bukan target; `target_margin_percent` baru rekomendasi desain dan belum tersedia.
- Mengubah `risk_percent` paper dari `0.5` menjadi `1.0`. Config valid, tetapi **service belum direstart**, jadi runtime lama belum tentu memuat nilai baru. Posisi lama tidak diubah.
- Tidak mengubah leverage ke 10x, tidak menambah `target_margin_percent`, tidak restart service, tidak mengubah live flags/state/history.

### File dibuat/diubah pada sesi ini
- **Dibuat:** `tests/test_dashboard_pnl_stream.py`.
- **Diubah:** `app/dashboard/static/dashboard.js`, `app/dashboard/templates/index.html`, `tests/test_dashboard_orders_scroll.py`, `configs/paper_trading.json`, `TASKS.md`, `SESSION_LOG.md`.
- Working tree juga memiliki perubahan/untracked dari sesi lama (`app/dashboard/static/dashboard.css`, test Orders, geometry/test terkait, dll.); review `git status` sebelum commit dan jangan overwrite perubahan yang bukan milik sesi ini.

### Command penting dan hasil
```bash
node --check app/dashboard/static/dashboard.js
# berhasil

.venv/bin/pytest tests/test_chart_proposal.py::test_scanner_chart_conflict_is_rejected_by_baseline_policy -q --tb=short
# 1 passed

.venv/bin/pytest tests/test_dashboard_orders_scroll.py -q --tb=short
# 8 passed setelah test denominator snapshot/realtime ditambah

.venv/bin/pytest tests/test_dashboard_pnl_stream.py tests/test_dashboard_orders_scroll.py -q --tb=short
# 11 passed

python -c 'import json; ... assert config["risk_percent"] == 1.0'
# VALID risk_percent=1.0

git diff --check -- app/dashboard/static/dashboard.js app/dashboard/templates/index.html tests/test_dashboard_orders_scroll.py tests/test_dashboard_pnl_stream.py configs/paper_trading.json
# bersih pada pengecekan terarah
```

### Error/masalah terakhir
- `risk_percent=1.0` baru tertulis di disk; realtime belum direstart untuk memuat config. Jangan menganggap posisi baru sudah memakai 1% sebelum restart dan verifikasi artifact.
- User mempertimbangkan leverage 10x agar margin tidak terlalu kecil, tetapi **leverage belum diubah**. Posisi lama harus mempertahankan leverage saat entry.
- `target_margin_percent` belum diimplementasikan. Jangan menyamakan “target margin 3%” dengan “risk 3%”; risk 3% berarti potensi rugi ke SL 3% per posisi dan jauh lebih agresif.
- Label persentase UI secara makna adalah ROE. Active Orders/P&L Stream sudah memakai rumus ROE, tetapi label eksplisit `ROE` belum ditambahkan.
- Dokumentasi Binance/Bitunix memblokir fetch otomatis; formula diverifikasi terhadap model kontrak linear dan implementasi lokal, tanpa kutipan palsu.
- Beberapa command tool sukses tetapi output tidak tertangkap; command terarah/test tetap hijau. Tetap gunakan command sempit agar RAM dan waktu rendah.

### Keputusan teknis
- Modal/margin exchange-style: `notional / leverage`; notional tidak boleh diberi label Modal.
- Unrealized PnL nominal tetap `(mark-entry) × quantity` (dibalik untuk SHORT); persentase panel adalah ROE `PnL / margin × 100`.
- Snapshot dan WebSocket harus memakai denominator yang sama agar tidak flicker/meloncat.
- `used_capital` menjadi sumber margin utama; fallback `abs(notional) / leverage`, lalu `entry × remaining_size / leverage`.
- Risk cap ke SL lebih penting daripada target modal. Jika kelak dibuat, `target_margin_percent` harus soft target dan tidak boleh menembus `risk_percent`.
- Perubahan config forward-looking: posisi lama/state/history tidak di-rewrite.
- Pemeriksaan/edit harus ringan: file terarah, test kecil, tanpa load JSONL besar atau service tambahan.

### Next step chat baru
1. Baca handoff ini dan entri terbaru `SESSION_LOG.md`; cek working tree sebelum edit/commit.
2. Jelaskan efek lalu restart **hanya** `crypto-quant-bot.service` jika user ingin `risk_percent=1.0` aktif; jangan restart API dan jangan mengubah live OFF.
3. Setelah restart, verifikasi posisi paper baru memiliki sizing risk ke SL ≤ sekitar 1% available balance, geometry/RR tetap valid, dan posisi lama tidak berubah.
4. Tanyakan/konfirmasi apakah user benar-benar mengubah leverage via Settings menjadi 10x. Jangan rewrite leverage posisi aktif.
5. Hard refresh browser lalu verifikasi visual: Entry conflict = REJECT, Active Orders Modal benar, PnL% tidak meloncat, dan P&L Stream sama dengan Active Orders.
6. Pertimbangkan mengganti label persentase menjadi `ROE` agar tidak disalahartikan sebagai perubahan harga atau return akun.
7. Jangan implementasikan `target_margin_percent` tanpa requirement eksplisit. Jika diminta: soft target 3%, hard risk cap 1%, cap margin 10%, serta test sizing/partial close.
8. Lanjutkan verifikasi runtime lama: `rr_tp1 >= 2`, geometry valid, `tp_level_source` deterministik, dan conflict artifact tetap `scanner_chart_conflict_rejected`.

---

## Handoff sesi 2026-07-28 — Orders scroll, mobile leverage badge, geometry runtime

### Sudah dikerjakan di sesi ini
- Membaca ulang `.clinerules`, konteks proyek/VPS, `TASKS.md`, dan `SESSION_LOG.md`; melanjutkan dari handoff geometry gate.
- Memverifikasi shared geometry gate dan tes Chart Proposal: **13 passed**.
- Menyelesaikan P1 observability close:
  - event `partial_close` menyimpan `close_scope="partial"` dan `close_label`;
  - event `closed` menyimpan `close_scope="full"` dan `close_label`;
  - raw `reason`/`partial_reason`/`close_reason` tetap dipertahankan;
  - fallback dashboard memberi label jelas untuk history lama.
- Mengaudit leverage paper dan menemukan Settings 25 sebelumnya di-cap internal menjadi 5x.
- Menghapus hard cap 5x: leverage eksplisit dari menu Settings sekarang dipakai aktual oleh posisi paper baru; bila kosong tetap default 1x.
- Restart realtime selesai; live tetap OFF, paper ON, state/history tidak dihapus, API tidak sengaja direstart pada batch leverage.
- Fix UI menu Orders (frontend-only, tanpa restart service): Active Orders dan Order History tidak lagi rebuild container scroll penuh setiap update; `price_update` tidak lagi render tabel Active Orders penuh; debounce snapshot Orders menjadi `800ms`; shell table dimount sekali lalu hanya `<tbody>`/card mobile yang dipatch; `keepScroll(...)` menjadi guard scroll.
- Menambahkan badge leverage pada kartu mobile Active Orders, sebaris di samping LONG/SHORT (`25x`), memakai `leverage` aktual dengan fallback `configured_leverage`.

### File dibuat/diubah pada working tree
- **Dibuat, masih untracked:** `app/risk/geometry.py`, `tests/test_entry_geometry.py`, `tests/test_dashboard_orders_scroll.py`.
- **Diubah:** `app/chart_agent/proposal.py`, `app/decision_agent/agent.py`, `app/risk/risk_agent.py`, `app/paper/realtime_engine.py`, `app/dashboard/services.py`, `app/dashboard/static/dashboard.js`, `app/dashboard/static/dashboard.css`, `tests/test_chart_proposal.py`, `tests/test_realtime_paper_engine.py`, `tests/test_dashboard_services.py`, `TASKS.md`, `SESSION_LOG.md`.
- Jangan lupa review/add file untracked saat commit. Tidak ada secret, paper state, atau trade history yang dihapus/di-rewrite.

### Command penting dan hasil
```bash
.venv/bin/python -m pytest tests/test_entry_geometry.py tests/test_chart_proposal.py -q --tb=short
# 13 passed
.venv/bin/python -m pytest tests/test_realtime_paper_engine.py tests/test_dashboard_services.py -q --tb=short
# 25 passed
.venv/bin/python -m pytest tests/test_realtime_paper_engine.py tests/test_trading_preferences.py -q --tb=short
# 26 passed
.venv/bin/python -m py_compile app/paper/realtime_engine.py app/dashboard/services.py tests/test_realtime_paper_engine.py tests/test_dashboard_services.py
# OK
node --check app/dashboard/static/dashboard.js
# OK
systemctl restart crypto-quant-bot.service
# restart berhasil; realtime memuat kode baru
.venv/bin/python -m pytest tests/test_dashboard_orders_scroll.py -q --tb=short
# 7 passed
.venv/bin/python -m pytest tests/test_dashboard_office.py -q --tb=short
# 10 passed
.venv/bin/python -m pytest tests/test_dashboard_services.py -q --tb=short
# 2 passed
```

### Error/masalah terakhir
- Open paper baru setelah restart belum terverifikasi memiliki `configured_leverage: 25` dan `leverage: 25`; unit test sudah membuktikan kontrak, tetapi artifact runtime masih perlu ditunggu.
- Verifikasi runtime geometry/Tier 1 pada open baru juga belum lengkap: cek `rr_tp1 >= 2`, geometry valid, source deterministik, dan conflict artifact.
- API sempat terdeteksi `deactivating / stop-sigterm` PID 3716, tetapi pada pengecekan final sudah pulih **active/running** PID 8039 tanpa tindakan tambahan. Realtime **active/running** PID 7990.
- Startup realtime mencatat warning futures `-2015` (API key/IP/permission) saat bootstrap; paper mode tetap berjalan dan live tetap OFF.
- Beberapa command luas `git`/`pytest`/`systemctl` pernah timeout pada tool 30 detik meski command sempit berikutnya berhasil.
- Dashboard static masih memerlukan hard refresh; perubahan mapper P1 + Orders scroll/leverage badge baru perlu browser memuat asset mtime terbaru.
- Gambar contoh badge leverage mobile dari user tidak sampai/attachment tidak terbaca; implementasi memakai pill netral exchange-style `25x` di samping LONG/SHORT. Jika user minta gaya persis, sesuaikan `.mc-lev` / `.mc-tags`.

### Keputusan teknis
- RR paper tetap Opsi C hybrid: TP rendah dinormalisasi, bukan hard reject; history lama tidak ditulis ulang.
- Shared geometry gate tetap RR minimum 2.0 dan fail-safe di RiskAgent.
- RR/source tetap audit-only dan tidak ditampilkan di Active Orders; SL percentage tetap tampil.
- Close history memakai metadata terstruktur plus label manusia, dengan backward compatibility untuk event lama.
- Nilai leverage eksplisit Settings bersifat authoritative untuk paper (rentang tervalidasi 1–125); tanpa pilihan tetap 1x.
- Leverage tidak menggantikan risk sizing: `risk_percent` dan `max_position_size_percent` tetap membatasi notional.
- Posisi lama mempertahankan leverage saat dibuka; hanya posisi baru memakai pilihan terbaru. Live tetap OFF.
- UI Orders: container scroll harus stabil; render hanya patch body/list, bukan replace wrapper via `innerHTML` penuh.
- Badge mobile Active Orders memakai `leverage` aktual lebih dulu agar posisi lama yang actual 5x tidak salah ditampilkan sebagai configured 25x; `configured_leverage` hanya fallback.

### Next step chat baru
1. Baca handoff ini dan bagian teratas `SESSION_LOG.md`; review working tree serta file untracked geometry/test/dashboard-orders-test.
2. Konfirmasi realtime dan API tetap active; status final masing-masing PID 7990 dan 8039. Restart hanya bila benar-benar tidak sehat dan setelah menjelaskan efeknya. Jangan mengubah live flags.
3. Minta user hard refresh dashboard dan cek menu Orders mobile: Active Orders/Order History tidak lompat ke atas, badge leverage tampil di samping LONG/SHORT.
4. Jika masih flicker saat posisi open/close, lanjut langkah 4 UI: patch per-baris berbasis key (`data-symbol` untuk Active Orders; id/time+symbol untuk Order History).
5. Pastikan realtime tetap active dan satu siklus pasca-restart selesai.
6. Tunggu open paper baru lalu verifikasi sekaligus:
   - `configured_leverage: 25` dan `leverage: 25` bila Settings tetap 25;
   - `rr_tp1 >= 2`, SL/TP geometry valid, dan `tp_level_source` deterministik;
   - posisi/history lama tidak berubah.
7. Verifikasi `logs/agent_pipeline.json`: conflict `scanner_chart_conflict_rejected`, baseline entry bukan `chart_llm_proposal`.
8. Setelah API sehat, hard refresh dashboard dan cek RR Planned tidak tampil, `SL x.xx%` tetap tampil, serta reason history menjadi `Partial close — ...` / `Full close — ...`.
9. Jika runtime hijau, lanjut P2: kurangi churn soft-entry/re-entry dan evaluasi `acr_invalidation_counter_cisd` terhadap premature exit.

---

## Handoff sesi 2026-07-27

### Handoff sesi terakhir — Tier 2 batch 3/4 dan keputusan UI
- Shared geometry gate sudah dibuat di `app/risk/geometry.py`: RR minimum 2.0, sisi SL/TP, SL 0,35–4,5%, dan level finite/positif.
- Chart Proposal, Decision Agent, dan RiskAgent final gate memakai validasi geometry yang sama.
- Active Orders sempat ditambahkan RR Planned + source, lalu atas keputusan user **dihapus dari UI**; `rr_tp1`/`tp_level_source` tetap audit-only di backend/state.
- Stop Loss tetap menampilkan `SL x.xx%` di Active Orders.
- Tes geometry + Chart Proposal terakhir: **13 passed**; JavaScript `node --check` berhasil.
- File baru yang perlu diperhatikan dan saat cek terakhir belum tracked Git: `app/risk/geometry.py`, `tests/test_entry_geometry.py`.
- File tracked yang berubah pada working tree terakhir: `app/chart_agent/proposal.py`, `app/decision_agent/agent.py`, `app/risk/risk_agent.py`, `app/dashboard/static/dashboard.js`, `tests/test_chart_proposal.py`, `TASKS.md`.

### Command penting sesi terakhir
```bash
cd /opt/crypto-quant-bot
.venv/bin/python -m pytest tests/test_entry_geometry.py tests/test_chart_proposal.py -q --tb=short
# 13 passed
.venv/bin/python -m py_compile app/risk/geometry.py app/chart_agent/proposal.py app/decision_agent/agent.py app/risk/risk_agent.py tests/test_entry_geometry.py
# OK
node --check app/dashboard/static/dashboard.js
# OK
git diff --check -- app/dashboard/static/dashboard.js
# bersih
```

### Masalah terakhir
- Restart realtime setelah perubahan Python belum dilakukan; proses aktif masih memerlukan restart untuk memuat shared geometry gate.
- Hard refresh browser diperlukan setelah perubahan `dashboard.js` agar RR Planned yang lama hilang dari cache.
- `git status/diff` kadang timeout di environment bila dijalankan luas.
- File geometry/test baru belum terdaftar di Git (`ls-files --error-unmatch` gagal); jangan lupa review/add saat proses commit.

### Next step chat baru
1. Baca ulang file ini dan `SESSION_LOG.md`.
2. Verifikasi working tree, khususnya file baru `app/risk/geometry.py` dan `tests/test_entry_geometry.py`.
3. Restart **hanya** `crypto-quant-bot.service` setelah menjelaskan efeknya/konfirmasi sesuai policy; jangan restart API.
4. Setelah restart, cek open baru di `logs/paper_state.json`/`logs/paper_trades.jsonl`: geometry valid, `rr_tp1 >= 2`, tanpa rewrite history lama.
5. Cek `logs/agent_pipeline.json`: conflict tetap `scanner_chart_conflict_rejected`, baseline entry bukan `chart_llm_proposal`.
6. Hard refresh dashboard dan pastikan kolom/metric RR Planned tidak tampil; `SL x.xx%` tetap tampil.
7. Lanjut P1 reason close partial/full dan P2 churn soft-entry bila verifikasi runtime hijau.

---

### Sudah dikerjakan
1. **Opsi C** di `RealtimePaperTradingEngine`: struktural jika TP1 RR >= 2, else floor TP1 ke 2R (+ isi 3R/4R bila perlu).
2. Fallback TP invalid diganti **2R/3R/4R** (bukan 1R/1.5R/2R).
3. Meta posisi open: `rr_tp1`, `tp_level_source` (`structural` | `normalized_min_rr`).
4. Tes paper engine: **23 passed** (low-RR floor, preserve RR>=2, farther structural).
5. Tier 1 baseline safety: LLM hanya veto ENTRY (tidak bisa veto EXIT), conflict scanner-chart `REJECT` ter-wire, level LLM adoption OFF, PolicyPatch shadow OFF.
6. Tes Tier 1: 4 targeted passed; `test_chart_proposal.py` 8 passed; compile + config validation OK.
7. Dashboard Agent Entry Candidates: guard anti-clobber snapshot + merge live/file dedup per symbol di `dashboard.js`; syntax JS OK.
8. Realtime restart selesai: `crypto-quant-bot.service` PID `22247 -> 24492`; API PID `22170` tidak direstart.

### Keputusan
- **Bukan hard-gate reject** untuk RR.
- **Opsi C (hybrid)** dipilih user.
- Live **OFF**. History **tidak di-rewrite**. Open lama tetap level lama sampai close.
- Baseline paper: Chart LLM proposal tetap direkam, tetapi level order deterministik; PolicyPatch shadow; konflik scanner-chart ditolak.

### Next step
1. ✅ **Restart `run_realtime` selesai** — service `crypto-quant-bot`, PID baru 24492, mode paper, live OFF.
2. ✅ Siklus agent pasca-restart selesai (`15:08:57 WIB`, 3 kandidat dievaluasi, 6 posisi dimonitor).
3. ⏳ Verifikasi open baru setelah Tier 1: `rr_tp1 >= 2`, geometry OK, `tp_level_source` deterministik/normalized.
4. P1: RR tetap audit-only; tidak ditampilkan di Active Orders sesuai keputusan UI.
5. P0 sisa: geometry gate scanner/decision/LLM; decision normalisasi RR.

Detail: **`SESSION_LOG.md`**.

---

## Status terakhir

### Runtime
| Komponen | Status | Catatan |
|----------|--------|---------|
| `run_realtime.py` | Jalan | Restart Tier 1 + Opsi C selesai; PID 24492 |
| `run_api.py` | Jalan | Dashboard/API internal |
| Live exchange orders | **OFF** | dry-run |
| Paper trading | **ON** | `logs/paper_state.json` |

### Fix yang sudah masuk
| Item | Status |
|------|--------|
| Panel LLM OUTPUT / slim insights / tail cache | Done |
| Sanitize TP salah sisi + guard partial | Done |
| Fallback TP risk multiples (2R/3R/4R) | Done |
| File konteks + SESSION_LOG | Done |
| **Opsi C: RR open min 1:2 di realtime paper** | Kode + tes + runtime restart |
| **Tier 1 agent safety baseline** | Kode + tes + runtime restart |
| **Agent Entry Candidates realtime guard + merge** | Kode JS + syntax check; perlu hard refresh browser |

---

## Todo

### P0 — Kualitas trade
- [x] **Selaraskan RR >= 1:2 saat open** (**Opsi C**) di `RealtimePaperTradingEngine`
- [x] Satu gerbang geometry bersama untuk Chart Proposal, Decision, dan RiskAgent final gate.
- [ ] Decision agent: jangan adopt plan RR < min tanpa normalisasi.
- [x] Restart realtime; service sehat, API tidak direstart, paper state utuh.
- [x] Verifikasi siklus agent pertama pasca-restart; 3 kandidat dievaluasi, 6 posisi dimonitor.
- [ ] Verifikasi open baru setelah Tier 1 `rr_tp1 >= 2` dan geometry OK.
- [x] Tier 2 batch 1: klasifikasi error candle fetch dan gate data multi-timeframe fail-closed.
- [x] Tier 2 batch 1: PolicyPatch memiliki cap operasional untuk entries/candidate samples.
- [x] Tier 2 batch 2: event `entry_candidate_processed` jadi tipe `EntryCandidateProcessed` (kontrak WS lowercase tetap) + audit `publish_status`/`event_publish_failed` tanpa `except: pass` senyap.
- [x] Tier 2 batch 3: shared geometry gate dengan RR minimum 2.0, SL side, SL% bounds, dan TP1 side.
- [ ] Tier 2 batch 4: verifikasi runtime open baru (menunggu restart realtime).

### P1 — Observability & UI
- [x] `sl_pct` tampil di Active Orders; RR/source tetap disimpan untuk audit tetapi tidak ditampilkan sesuai keputusan UI.
- [x] Reason close partial vs full jelas di history: event menyimpan `close_scope`/`close_label`, raw `reason` tetap audit-compatible, dan dashboard memiliki fallback untuk history lama.
- [x] Fix scroll menu Orders tersendat + selalu kembali ke atas (Active Orders & Order History): shell tabel di-mount sekali, hanya `<tbody>`/card mobile yang dipatch, `price_update` tidak lagi rebuild tabel, debounce snapshot orders 100ms → 800ms. Frontend-only; perlu hard refresh, tanpa restart service.
- [x] Badge leverage di kartu mobile Active Orders, sebaris tepat di samping badge LONG/SHORT (`.mc-tags` + `.mc-lev`, format `25x`). Sumber `leverage` aktual dengan fallback `configured_leverage`; badge disembunyikan bila tidak ada nilai valid (mis. pending order).

### P2 — Stabilitas paper
- [x] Paper leverage mengikuti nilai eksplisit di menu Settings (1–125); tanpa pilihan tetap default 1x. Posisi lama tidak diubah.
- [ ] Verifikasi artifact open baru pasca-restart: Settings 25 menghasilkan `configured_leverage: 25` dan `leverage: 25`.
- [ ] Kurangi churn soft-entry / re-entry.
- [ ] Evaluasi `acr_invalidation_counter_cisd` vs premature exit.
- [ ] Reset paper state hanya setelah RR stabil + backup.

### P3 — Produksi
- [ ] Live tetap OFF sampai paper + RR stabil.
- [ ] Kill switch, reconciliation, permission bertahap.

---

## Masalah saat ini

1. **Proses realtime belum restart** — kode Opsi C di disk; open baru sehat setelah restart. Open lama tidak dinormalisasi ulang.
2. Historis TP terbalik UNI — fixed forward-looking.
3. Churn invalidation — P2.
4. Equity paper historis rendah — akumulasi.
5. Live off (sengaja).

---

## Next step

1. Hard refresh dashboard sekali agar `dashboard.js` guard+merge aktif.
2. Verifikasi open baru setelah restart Tier 1: `rr_tp1 >= 2`, `tp_level_source` deterministik/normalized_min_rr.
3. Cek konflik scanner-chart baru benar-benar `scanner_chart_conflict_rejected` di artifact.
4. Verifikasi shared geometry gate setelah restart realtime; RR tetap audit-only di UI.

```bash
cd /opt/crypto-quant-bot
.venv/bin/python -m pytest tests/test_realtime_paper_engine.py -q
```

---

## Catatan kerja

- Jangan expose / commit secret.
- Restart service hanya setelah ubah Python runtime. Tier 1 restart sudah dilakukan; live tetap OFF.
- `PROJECT_CONTEXT.md` · `VPS_CONTEXT.md` · `.clinerules` · `SESSION_LOG.md`.

## Handoff sesi 2026-08-03 — Paper↔Live parity, lifecycle controller, EXIT gate bersama, live runner ON

### Sudah dikerjakan di sesi ini
- Audit mode paper: winrate tinggi karena tidak ada fee/spread/slippage/funding; SL/TP snap per siklus ±60s; state historis 10 USDT vs config 10.000, leverage 5x vs 25x.
- Kontrak lifecycle bersama (lifecycle_contract.py): LIFECYCLE_VERSION=paper_live_lifecycle_v1, TP_FRACTIONS=(0.30,0.30,0.40), execute_exit_gate.
- Executor full TP ladder TP1/TP2/TP3 reduce-only, entry live diblokir bila plan tidak lolos parity validation.
- Bitunix TP/SL primitives: GET pending TPSL, modify order, cancel order. Post-mutation verification via GET. BE/trailing = modify-in-place, tighten_stop=tighten-only.
- HOLD state machine persisten (live_lifecycle.py): LiveLifecycleStore keyed by positionId, idempotent resume, replace remaining ladder dari exchange.
- Shared BE/trailing (acr_engine_bridge.py) dipakai paper & live agar target identik.
- Registrasi lifecycle hanya untuk posisi baru v1; legacy ENA/DOGE tidak terdampak.
- Refactor EXIT gate bersama (execute_exit_gate): IMMEDIATE lolos; NEXT_CANDLE skip umur < min_hold(300s) atau -0.3R<pnl_ratio<=1.0R.
- Aktivasi live: paper_parity_verified=True di run_realtime.py; wiring runtime memproses HOLD lifecycle v1 saat live+network+execute_decisions.
- Restart runner bersih dari double instance, berjalan tunggal Mode live.

### File dibuat/diubah pada sesi ini
- Dibuat: app/execution/lifecycle_contract.py, app/execution/live_lifecycle.py, tests/test_lifecycle_contract.py, tests/test_live_lifecycle.py
- Diubah: executor_agent/agent.py, models.py, bitunix_futures_adapter.py, paper/realtime_engine.py, strategies/acr_engine_bridge.py, agent_pipeline/bridge.py, run_realtime.py
- Test: test_executor_agent.py, test_bitunix_futures_adapter.py, test_realtime_paper_engine.py, test_agent_pipeline_bridge.py

### Command penting dan hasil
.venv/bin/python -m pytest ... -q --tb=short
........................................................................ [ 61%]
.............................................                            [100%]
117 passed in 2.25s

# Runtime akhir: single instance Mode live, dashboard port 8899
