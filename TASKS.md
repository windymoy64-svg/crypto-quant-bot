# TASKS — Crypto Quant Bot

> Update file ini setiap selesai batch kerja.  
> Tujuan: status operasional + antrian kerja tanpa menebak-nebak.

**Terakhir di-update:** 2026-07-29 (agent conflict UI, Orders margin/ROE, P&L Stream ROE, paper risk 1%)
**Environment:** `/opt/crypto-quant-bot` (VPS Linux)

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
