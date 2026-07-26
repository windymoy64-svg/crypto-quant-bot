# TASKS — Crypto Quant Bot

> Update file ini setiap selesai batch kerja.  
> Tujuan: status operasional + antrian kerja tanpa menebak-nebak.

**Terakhir di-update:** 2026-07-27 (Opsi C RR normalize di pintu open paper)  
**Environment:** `/opt/crypto-quant-bot` (VPS Linux)

---

## Handoff sesi 2026-07-27

### Sudah dikerjakan
1. **Opsi C** di `RealtimePaperTradingEngine`: struktural jika TP1 RR >= 2, else floor TP1 ke 2R (+ isi 3R/4R bila perlu).
2. Fallback TP invalid diganti **2R/3R/4R** (bukan 1R/1.5R/2R).
3. Meta posisi open: `rr_tp1`, `tp_level_source` (`structural` | `normalized_min_rr`).
4. Tes paper engine: **23 passed** (low-RR floor, preserve RR>=2, farther structural).

### Keputusan
- **Bukan hard-gate reject** untuk RR.
- **Opsi C (hybrid)** dipilih user.
- Live **OFF**. History **tidak di-rewrite**. Open lama tetap level lama sampai close.

### Next step
1. **Restart `run_realtime`** agar kode baru ter-load.
2. Verifikasi open **baru**: `rr_tp1 >= 2`, geometry OK.
3. P1: kolom RR planned di Active Orders.
4. P0 sisa: geometry gate scanner/decision/LLM; decision normalisasi RR.

Detail: **`SESSION_LOG.md`**.

---

## Status terakhir

### Runtime
| Komponen | Status | Catatan |
|----------|--------|---------|
| `run_realtime.py` | Jalan (kode lama di memori?) | **Perlu restart** agar Opsi C aktif |
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
| **Opsi C: RR open min 1:2 di realtime paper** | Kode + tes (perlu restart runtime) |

---

## Todo

### P0 — Kualitas trade
- [x] **Selaraskan RR >= 1:2 saat open** (**Opsi C**) di `RealtimePaperTradingEngine`
- [ ] Satu gerbang geometry (scanner / decision / LLM / percent).
- [ ] Decision agent: jangan adopt plan RR < min tanpa normalisasi.
- [ ] Restart realtime + verifikasi open baru `rr_tp1 >= 2`.

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

1. Restart **hanya** `run_realtime` (setelah konfirmasi).
2. Verifikasi open baru: `rr_tp1 >= 2`, `tp_level_source` structural|normalized_min_rr.
3. Lanjut P0 geometry / decision bila open baru sehat.

```bash
cd /opt/crypto-quant-bot
.venv/bin/python -m pytest tests/test_realtime_paper_engine.py -q
```

---

## Catatan kerja

- Jangan expose / commit secret.
- Restart service hanya setelah ubah Python runtime.
- `PROJECT_CONTEXT.md` · `VPS_CONTEXT.md` · `.clinerules` · `SESSION_LOG.md`.
