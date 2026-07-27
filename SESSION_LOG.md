# SESSION_LOG — Crypto Quant Bot

> Catatan sesi kerja untuk handoff chat/agent berikutnya.  
> Entri baru di **atas** (terbaru dulu). Jangan hapus entri lama yang masih relevan.  
> **Jangan** menyimpan password, token, API key, atau secret.

---

## Sesi 2026-07-27 — Handoff akhir: dashboard realtime, Tier 1, restart runtime

**Environment:** `/opt/crypto-quant-bot`  
**Mode akhir:** paper ON · live OFF · executor dry-run  
**Runtime:** realtime PID `24492`; API PID `22170`

### 1. Sudah dikerjakan di sesi ini

#### Dashboard / Agents Entry Candidates
- Ditemukan root cause Entry Candidates telat: event WebSocket realtime ditimpa snapshot `agent_snapshot` periodik dari `logs/agent_pipeline.json` yang masih memakai siklus lama.
- `app/dashboard/static/dashboard.js` diperbaiki dengan:
  - timestamp `lastEntryLiveTs` untuk event `entry_candidate_processed`;
  - guard agar snapshot lama tidak menimpa data live;
  - merge live + file saat live lebih baru, dedup per symbol, live diprioritaskan; baris file seperti `skip`/missing candles tetap tampil.
- Node syntax check: `SYNTAX_OK`.
- Perlu hard refresh browser sekali untuk mengambil asset static terbaru; tidak perlu restart API untuk perubahan JS.

#### Tier 1 baseline agent safety
- Decision LLM hanya dapat veto `ENTRY_BUY`/`ENTRY_SELL`; tidak dapat mengubah `EXIT` menjadi `HOLD`.
- `scanner_chart_conflict_policy` ditambahkan ke runtime config, validasi enum `REJECT|WATCH|IGNORE`, default/baseline `REJECT`, dan di-wire ke coordinator melalui bridge + `run_realtime`.
- `adopt_chart_proposal_levels=false`: proposal Chart LLM tetap direkam/audit, tetapi entry/SL/TP order memakai level deterministik.
- `apply_llm_policy=false`: PolicyPatch shadow, tidak mengubah decision.
- Default fail-safe adopsi level Chart LLM juga diubah menjadi `false` di bridge/coordinator/run_realtime.

#### Runtime / RR
- Restart hanya `crypto-quant-bot.service`: PID `22247 -> 24492`; `crypto-quant-bot-api.service` tidak disentuh.
- Startup validation OK; mode paper; live tetap OFF; paper state utuh dengan 6 posisi.
- Lima posisi non-legacy punya `rr_tp1=2.0`, `tp_level_source=normalized_min_rr`; posisi U legacy tidak di-rewrite.
- Siklus agent pasca-restart selesai pada `15:08:57 WIB`: 3 kandidat dievaluasi, 6 posisi dimonitor.

### 2. File dibuat/diubah
- `app/agent_pipeline/coordinator.py`
- `app/agent_pipeline/bridge.py`
- `run_realtime.py`
- `configs/realtime.json`
- `tests/test_chart_proposal.py`
- `tests/test_agent_pipeline_bridge.py`
- `app/dashboard/static/dashboard.js`
- `TASKS.md`
- `SESSION_LOG.md`

Tidak ada file secret atau history paper yang dihapus/ditulis ulang.

### 3. Command penting
```bash
# Validasi Tier 1 targeted
.venv/bin/python -m pytest \
  tests/test_chart_proposal.py::test_decision_llm_veto_blocks_entry \
  tests/test_chart_proposal.py::test_decision_llm_cannot_veto_exit \
  tests/test_chart_proposal.py::test_scanner_chart_conflict_is_rejected_by_baseline_policy \
  tests/test_agent_pipeline_bridge.py::test_conflict_policy_defaults_to_reject_and_validates_enum \
  -q --tb=line
# 4 passed; kemudian subset gabungan 6 passed

.venv/bin/python -m pytest tests/test_chart_proposal.py -q --tb=line
# 8 passed

.venv/bin/python -m pytest tests/test_realtime_paper_engine.py -q
# 23 passed pada batch RR sebelumnya

.venv/bin/python -m py_compile app/agent_pipeline/bridge.py \
  app/agent_pipeline/coordinator.py run_realtime.py
# OK

systemctl restart crypto-quant-bot.service
systemctl --no-pager --full status crypto-quant-bot.service
systemctl --no-pager --full status crypto-quant-bot-api.service
journalctl -u crypto-quant-bot.service -n 35 --no-pager -o cat
# realtime active, API tetap active, startup + scan berjalan
```

### 4. Error / masalah terakhir
- Full `tests/test_agent_pipeline_bridge.py` sempat timeout di environment; test config Tier 1 baru lulus dan compile lulus.
- Beberapa command luas (`git diff/status`, pytest gabungan besar) juga timeout; tidak ada error test terarah dari Tier 1.
- Futures bootstrap warning nonfatal: API permission error `-2015` untuk `position_mode` dan `multi_assets_margin`; service tetap active, paper/live safety tidak berubah.
- Artifact `logs/agent_pipeline.json` sempat masih timestamp sebelum restart saat pengecekan awal; setelah itu journal menunjukkan siklus agent baru selesai.
- Posisi U legacy tidak memiliki `rr_tp1`; history/state lama sengaja tidak di-rewrite.

### 5. Keputusan teknis
- RR: Opsi C hybrid, bukan hard reject; TP1 minimal 2R, level struktural >=2R dipertahankan.
- Baseline paper harus deterministik: Chart LLM boleh propose/audit, tidak boleh mengganti level order.
- PolicyPatch tetap shadow.
- Konflik scanner vs chart deterministic default `REJECT`.
- Decision LLM hanya veto entry; mandatory/structural exit tidak boleh diveto.
- Live tetap OFF sampai paper, RR, risk, data quality, dan observability stabil.
- Paper history dan legacy positions tidak di-rewrite.

### 6. Next step chat baru
1. Hard refresh browser sekali; buka Agents dan pastikan Entry Candidates live tidak lagi mundur saat snapshot 5 detik masuk.
2. Verifikasi artifact `logs/agent_pipeline.json` pasca-restart: conflict menghasilkan `scanner_chart_conflict_rejected`, dan entry source tidak `chart_llm_proposal` untuk baseline.
3. Pantau open baru di `logs/paper_state.json`/`logs/paper_trades.jsonl`: `rr_tp1 >= 2`, geometry OK, tanpa menyentuh history lama.
4. Lanjut Tier 2: klasifikasi error candle fetch (jangan `except -> []`), data quality gate minimal, logging publish event, dan batas PolicyPatch.
5. P1 dashboard: kolom RR planned di Active Orders dan source/sl_pct observability.
6. Tetap jangan restart API/live atau mengubah permission futures tanpa kebutuhan dan konfirmasi.

---

## Sesi 2026-07-27 — Tier 1 baseline safety agent pipeline

**Mode:** paper ON · live OFF · realtime sudah restart

### Selesai
- Decision LLM hanya boleh veto `ENTRY_BUY`/`ENTRY_SELL`; `EXIT` selalu dipertahankan.
- `scanner_chart_conflict_policy` ditambah ke runtime config, enum `REJECT|WATCH|IGNORE`, default/config baseline `REJECT`, dan ter-wire ke coordinator di bridge + `run_realtime`.
- `adopt_chart_proposal_levels=false` (juga default fail-safe false); proposal Chart LLM tetap audit/shadow.
- `apply_llm_policy=false` baseline shadow.
- Tests: Tier 1 targeted 4 passed; full `test_chart_proposal.py` 8 passed; py_compile + JSON/runtime config validation OK.
- Full `test_agent_pipeline_bridge.py` sempat timeout di environment; test config baru sendiri lulus.

### Runtime verification
- Restart hanya `crypto-quant-bot.service`; PID 22247 → 24492. API tetap PID 22170.
- Startup: production validation OK, `Mode paper`; live execution config false.
- Paper state utuh: 6 posisi. Lima posisi non-legacy punya `rr_tp1=2.0`; U legacy tidak di-rewrite.
- Baseline runtime config: adoption false, policy false, conflict REJECT.
- Warning nonfatal: futures bootstrap API permission `-2015`; service tetap active dan paper scan berjalan.
- Artifact agent saat cek masih timestamp sebelum restart (siklus baru belum selesai).

### Next
- Verifikasi artifact siklus agent pertama pasca-restart + entry source deterministik/conflict reject; pantau open baru RR >= 2.

---

## Sesi 2026-07-27 — Opsi C RR normalize di pintu open paper

**Environment:** `/opt/crypto-quant-bot` (VPS Linux)  
**Mode bot:** paper ON · live OFF · executor dry-run  
**Handoff:** restart `run_realtime` + verifikasi open baru

### 1. Apa yang dikerjakan
- Diskusi: hard gate **tidak wajib** untuk RR 1:2; cukup bentuk TP di sistem sekarang.
- User setuju **Opsi C (hybrid)** (bukan A always-2R, bukan B reject).
- Implement di `app/paper/realtime_engine.py`:
  - `_normalize_take_profits_min_rr` — keep structural jika TP1 RR ≥ 2, else floor 2R + keep farther + fill 3R/4R.
  - `_risk_multiple_levels` / fallback → **2R/3R/4R**.
  - Position meta: `rr_tp1`, `tp_level_source`.
- Tes: update inverted/fallback/empty-overrides; tambah low-RR, structural preserve, farther keep.
- `pytest tests/test_realtime_paper_engine.py -q` → **23 passed**.

### 2. File diubah
- `app/paper/realtime_engine.py`
- `tests/test_realtime_paper_engine.py`
- `TASKS.md`, `SESSION_LOG.md`

### 3. Belum
- Restart proses realtime (kode baru belum di memori proses lama).
- Verifikasi live open baru di trades/state.
- Geometry gate lintas scanner/decision/LLM (P0 sisa).

### 4. Next step
1. Restart hanya `run_realtime` (minta konfirmasi bila policy VPS).
2. Cek open baru: `rr_tp1 >= 2`.
3. P1 UI RR planned opsional.

---


## Sesi 2026-07-26 — Dashboard LLM, paper TP/trailing, konteks project

**Environment:** `/opt/crypto-quant-bot` (VPS Linux)  
**Mode bot akhir sesi:** paper ON · live OFF · executor dry-run  
**Handoff:** lanjut chat baru dari **Next step** + `TASKS.md`

---

### 1. Apa yang dikerjakan

#### A. Panel LLM — kolom OUTPUT kosong (`-`)
- **Gejala:** Insight History tampil agent/model tapi OUTPUT `-`.
- **Akar:** LLM menyimpan `output.policy_patch.human_summary`; UI hanya baca `summary`/`explanation`/`reason`/`analysis`.
- **Fix:** normalize+slim API; drop `input_summary`; JS `llmInsightDisplay`/`agentClip`; `latest()` via tail cache.

#### B. Trailing + minus (UNI LONG)
- **Gejala:** Badge TRAILING + uPnL merah; PARTIAL `take_profit_1` minus lalu CLOSED invalidation.
- **Akar:** TP1 LONG **di bawah entry** → partial rugi → `trailing_active=True`.
- **Fix di `RealtimePaperTradingEngine`:** sanitize TP, fallback 1R/1.5R/2R, guard partial/legacy profitable-only.

#### C. RR & arsitektur
- Desain min RR 2 ada di RiskManager/strategi; **paper realtime tidak lewat RiskManager** → open RR 0.6–0.9.
- User: **tidak wajib hard gate reject** — prefer **bentuk RR 1:2** (paksa/geser TP) di sistem sekarang.
- **Keputusan next:** Opsi A/C (normalize TP ke 2R), bukan prioritas Opsi B (reject-only).

#### D. Audit status bot
- API + realtime jalan; live off; open sample U RR≈3 OK, ZEC/ALLO RR&lt;1; equity paper historis rendah.

#### E. File konteks
- Dibuat: `TASKS.md`, `PROJECT_CONTEXT.md`, `VPS_CONTEXT.md`, `.clinerules`.

---

### 2. File dibuat / diubah

**Dibuat:** `TASKS.md`, `PROJECT_CONTEXT.md`, `VPS_CONTEXT.md`, `.clinerules`, `SESSION_LOG.md`

**Diubah:**
- `app/dashboard/routes/agent.py` — slim/normalize LLM insights
- `app/dashboard/static/dashboard.js` — render OUTPUT LLM
- `app/learning_agent/insight_store.py` — `latest()` tail cache
- `app/paper/realtime_engine.py` — sanitize/fallback TP + guard partial
- `tests/test_dashboard_agent_routes.py`, `tests/test_settings_ui.py`
- `tests/test_memory_bounds.py`, `tests/test_realtime_paper_engine.py`

**Tidak diubah (sengaja):** history paper trades; live flags; hard-gate RR reject-only.

---

### 3. Command penting

```bash
cd /opt/crypto-quant-bot
.venv/bin/python -m pytest tests/test_realtime_paper_engine.py -q
# 20 passed (termasuk inverted TP)

.venv/bin/python -m pytest \
  tests/test_realtime_paper_engine.py::test_inverted_long_tp_is_sanitized_and_rebuilt \
  tests/test_realtime_paper_engine.py::test_all_inverted_tps_fall_back_to_risk_multiples \
  tests/test_dashboard_agent_routes.py::test_llm_insights_returns_recent_rows \
  tests/test_dashboard_agent_routes.py::test_llm_insights_flattens_policy_patch_for_ui -q
# 4 passed

# Inspeksi: tail paper_trades / paper_state / agent_pipeline (jangan load full JSONL besar)
# Restart run_api / run_realtime agar kode baru ter-load (jangan dump .env / API key)
```

Beberapa command luas sempat **timeout** di agent env; tes terarah lulus.


---

### 4. Error / masalah terakhir

| Masalah | Status |
|---------|--------|
| LLM OUTPUT `-` | ✅ Fixed |
| UNI TP terbalik → partial minus + trailing | ✅ Fixed di kode (open baru) |
| Shell/API timeout di env agent | ⚠️ Mitigasi: command sempit, baca state file |
| HTTP 401 API tanpa key | Expected |
| Open paper RR < 2 (ZEC, ALLO, historis) | ❌ **Belum** — next step |
| Churn invalidation cepat | ❌ Open (P2) |
| Equity paper historis rendah | ❌ Open (akumulasi) |
| Realtime paper ≠ RiskManager path | ❌ Ditutup sebagian lewat normalize TP next |

**#1 chat baru:** RR open tidak dijamin 1:2.

---

### 5. Keputusan teknis

1. LLM UI harus paham skema `policy_patch`.
2. Payload insight dashboard harus slim (no journal snapshot).
3. TP wajib sisi profit; partial/trailing tidak dari level terbalik.
4. Target RR sehat min ~1:2 (1:3+ situasional).
5. **Next RR fix = set/geser TP ke 1:2 (Opsi A/C), bukan wajib hard reject (Opsi B).**
6. Live tetap OFF sampai paper+RR stabil.
7. Jangan rewrite history trades; fix forward-looking.
8. Konteks jangka panjang: TASKS + PROJECT_CONTEXT + VPS_CONTEXT + .clinerules.

---

### 6. Next step (chat baru)

1. Baca `TASKS.md`, `PROJECT_CONTEXT.md`, `.clinerules`, entri sesi ini.
2. Di `app/paper/realtime_engine.py` setelah entry+SL final: normalisasi **TP1 = 2R** (opsional TP2/3 = 3R/4R) atau hybrid struktural-if-≥2R-else-2R; SKIP hanya jika SL/risk invalid.
3. Extend tests paper engine (signal RR jelek → open TP1 ≥ 2R).
4. Restart hanya `run_realtime` (jelaskan efek dulu bila perlu).
5. Verifikasi tail `logs/paper_trades.jsonl`: geometry OK + RR_TP1 ≥ 2.
6. Update `TASKS.md` + entri singkat di `SESSION_LOG.md`.

**Bukan prioritas:** live trading, hapus paper history, expose API publik.

---

### 7. Pointer file

| Butuh | Buka |
|-------|------|
| Antrian | `TASKS.md` |
| Arsitektur | `PROJECT_CONTEXT.md` |
| VPS | `VPS_CONTEXT.md` |
| Aturan agent | `.clinerules` |
| Paper open/TP | `app/paper/realtime_engine.py` |
| Risk formal | `app/risk/manager.py`, `configs/paper.json` |
| LLM panel | `app/dashboard/routes/agent.py`, `static/dashboard.js` |
| State paper | `logs/paper_state.json`, `logs/paper_trades.jsonl` |

### 8. Verifikasi hijau di sesi

- Unit test inverted UNI: TP di atas entry; harga di bawah entry tidak partial/trailing.
- `recent_llm_insights`: summary dari human_summary; no input_summary di response.
- pytest paper engine: **20 passed**.

*Akhir entri sesi 2026-07-26.*
