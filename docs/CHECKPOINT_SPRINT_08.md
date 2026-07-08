# Checkpoint Sprint 08

Status: completed as documentation checkpoint.

Tanggal checkpoint: 2026-07-06.

## Ringkasan

Sprint 08 menyelesaikan lapisan explainable scoring yang lebih kaya tanpa mengubah prinsip utama platform. Bot tetap deterministic, tidak melakukan live trading otomatis, dan semua output penting tetap JSON-ready.

Fitur utama Sprint 08:

- Market regime classification.
- Dynamic rule weights berdasarkan regime.
- Multi-timeframe scanner.
- Rule explanation pada hasil scoring.
- Feature importance dari kontribusi rule.

## File Dan Area Terkait

- `app/market/regime.py` untuk klasifikasi market regime.
- `app/scoring/dynamic_weights.py` untuk profil bobot rule.
- `configs/rule_weights.json` untuk konfigurasi dynamic weights.
- `app/market/multi_timeframe.py` untuk scan beberapa timeframe dan agregasi score.
- `app/scoring/feature_importance.py` untuk kontribusi feature.
- `scan_market.py` untuk output market regime, weight profile, score, rule explanation, dan feature importance.
- `tests/test_market_regime.py` untuk coverage regime.
- `tests/test_dynamic_weights.py` untuk coverage dynamic weights dan export rule.
- `tests/test_feature_importance.py` untuk coverage feature importance.

## Behavior Yang Sudah Tersedia

- Scanner bisa menilai beberapa symbol dan beberapa timeframe.
- Result menyimpan `market_regime`, `weight_profile`, `signals`, `rules`, `feature_importance`, `final_score`, `final_confidence`, `trend_alignment`, dan `overall_action`.
- Rule result menyimpan reason agar scoring dapat dijelaskan.
- Dynamic weight tidak menghapus base rule; applied weight dicatat agar audit tetap jelas.
- Feature importance mengelompokkan kontribusi rule ke kategori feature.

## Boundary Yang Tidak Diubah

- Tidak ada live order otomatis.
- Tidak ada API key yang dibutuhkan untuk scan publik.
- Fallback sample data tetap tersedia.
- LLM tetap tidak mengambil keputusan trading.
- Execution engine tetap hanya membaca signal.

## Catatan Recovery Mode

Task dokumentasi ini dibuat dalam recovery mode setelah kegagalan command environment-specific.

Instruksi yang berlaku untuk checkpoint ini:

- Tidak memakai `rg`, `fd`, `grep`, `sed`, `awk`, atau `jq`.
- Tidak menjalankan Python REPL atau raw Python source di PowerShell.
- Tidak menjalankan `pytest`.
- Tidak menjalankan `compileall`.
- Tidak memakai `git`.
- Tidak memodifikasi source code.

## Sprint Berikutnya

Sprint 09 belum dimulai.

Fokus yang disarankan untuk Sprint 09 adalah ranking portofolio dan kandidat trade lintas symbol berdasarkan output Sprint 08. Sprint 09 sebaiknya hanya dimulai setelah checkpoint ini diterima.

## Done Criteria Sprint 08

- Market regime tersedia di output multi-timeframe.
- Dynamic weights bisa dipilih berdasarkan regime.
- Rule explanation tersedia untuk audit scoring.
- Feature importance tersedia di payload JSON.
- Scanner menampilkan ringkasan explainability di console.
- Dokumentasi checkpoint dibuat di folder `docs/`.