# TASKS — Crypto Quant Bot

> Update file ini setiap selesai batch kerja.  
> Tujuan: status operasional + antrian kerja tanpa menebak-nebak.

**Terakhir di-update:** 2026-07-27 (Tier 2 batch 1 — data quality + PolicyPatch bounds)  
**Environment:** `/opt/crypto-quant-bot` (VPS Linux)

---

## Handoff sesi 2026-07-27

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
4. P1: kolom RR planned di Active Orders.
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
- [ ] Satu gerbang geometry (scanner / decision / LLM / percent).
- [ ] Decision agent: jangan adopt plan RR < min tanpa normalisasi.
- [x] Restart realtime; service sehat, API tidak direstart, paper state utuh.
- [x] Verifikasi siklus agent pertama pasca-restart; 3 kandidat dievaluasi, 6 posisi dimonitor.
- [ ] Verifikasi open baru setelah Tier 1 `rr_tp1 >= 2` dan geometry OK.
- [x] Tier 2 batch 1: klasifikasi error candle fetch dan gate data multi-timeframe fail-closed.
- [x] Tier 2 batch 1: PolicyPatch memiliki cap operasional untuk entries/candidate samples.
- [ ] Tier 2 batch 2: audit subscriber/logging publish event dan geometry gate lintas jalur.

### P1 — Observability & UI
- [ ] Kolom **RR planned** di Active Orders.
- [ ] Log `sl_pct` / source kaya; `rr_tp1` sudah di position.
- [ ] Reason close partial vs full jelas di history.

### P2 — Stabilitas paper
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
4. Lanjut P0 geometry/data-quality gate dan P1 RR planned UI.

```bash
cd /opt/crypto-quant-bot
.venv/bin/python -m pytest tests/test_realtime_paper_engine.py -q
```

---

## Catatan kerja

- Jangan expose / commit secret.
- Restart service hanya setelah ubah Python runtime. Tier 1 restart sudah dilakukan; live tetap OFF.
- `PROJECT_CONTEXT.md` · `VPS_CONTEXT.md` · `.clinerules` · `SESSION_LOG.md`.
