# Checkpoint Sprint 24 - Strategy Doc (Liquidity + S/R + Trend + MTF)

## Ruang Lingkup

Sprint ini hanya menulis spesifikasi strategi baru sebagai dokumen. Tidak ada
perubahan kode aplikasi, konfigurasi rule, payload signal, atau perilaku
runtime. Dokumen menjadi single source of truth untuk sprint implementasi
berikutnya (indikator, strategi, rule scoring, integrasi realtime).

## Files Changed

- `docs/strategy_liquidity_sr_mtf.md` (baru) - spesifikasi strategi
  "Liquidity + Support/Resistance + Trend + Multi-Timeframe", termasuk
  kontrak data untuk indikator, strategi, dan rule scoring, ditambah aturan
  mutlak (hard-gate) untuk anchor S/R dan fresh liquidity.
- `docs/CHECKPOINT_SPRINT_24_STRATEGY_DOC.md` (baru) - checkpoint ini.
- `docs/ROADMAP.md` - tambah entri Sprint 24 di daftar "Selesai" dan
  penjelasan rencana bertahap Sprint 25 sampai 28 di kandidat berikutnya.

## Summary

- Strategi dijabarkan dalam 11 section: konsep inti, arah tren, MTF,
  alur entry, konfirmasi, aturan mutlak, kontrak data, risiko, safety
  boundary, rencana implementasi bertahap, dan catatan.
- Aturan mutlak diformalkan menjadi mekanisme veto di `ScoreEngine` untuk
  sprint berikutnya: `rule_price_at_sr_zone` dan
  `rule_fresh_liquidity_present` fail memaksa `action` menjadi `HOLD`
  walau skor tinggi. Ini menjaga aturan "confidence tanpa anchor = bukan
  setup".
- Kontrak indikator (swing points, structure state, S/R zones, liquidity
  pools, sweep events) didefinisikan sebagai fungsi pure yang menghasilkan
  struktur JSON-serializable, konsisten dengan prinsip deterministic proyek.
- MTF mengikuti pola yang sudah dipakai `MultiTimeframeScanner`; TF besar
  selalu menang. Sinyal TF kecil yang melawan bias TF besar wajib di-skip.
- Rencana implementasi dipecah menjadi 5 sprint terpisah agar tiap sprint
  hanya menyelesaikan satu area, sesuai `CLAUDE.md`.

## Tests

Sprint dokumen tidak menambah kode.

- `./.venv/bin/python -m compileall app tests` - tidak dijalankan karena
  tidak ada perubahan `.py`. Baseline sebelumnya (dari Sprint 23) tetap
  bersih.
- `./.venv/bin/python -m pytest` - tidak dijalankan karena tidak ada
  perubahan kode. Baseline sebelumnya (66/66) tetap berlaku.

## Follow-up

Sprint 25 (indikator baru) mengikuti kontrak di section 7.1 dokumen strategi.
Sprint 25 akan menambahkan kode dan wajib menjalankan compileall + pytest
sebelum ditutup.
