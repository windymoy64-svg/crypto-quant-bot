# Strategi Auden Candle Range Plus (ACR+)

Implementasi metodologi **ACR+** dari AudenFX Mentorship (sumber:
`docs/pdf/ACR - *.pdf`). Modul ini deterministic, pure, tanpa I/O, dan
dapat langsung dipakai untuk backtest, paper, atau live trading melalui
`RiskManager` yang sudah ada.

## Ringkasan File

| File | Isi |
| --- | --- |
| `app/indicators/acr.py` | Primitives: `acr_swings`, `fair_value_gaps`, `cisd_levels`, `mss_events`, `opposing_candles`, `latest_acr_pattern`, `latest_equilibrium_range`, `has_displacement_fvg`. |
| `app/strategies/acr_plus.py` | Evaluator utama: `evaluate(ACRPlusContext) -> ACRPlusDecision`. Menghasilkan sinyal BUY / SELL / HOLD lengkap dengan Entry / SL / TP1 / TP2 / TP3. |
| `app/strategies/acr_position_manager.py` | State machine posisi aktif: partial TP, break-even, trailing SL, hold decision, invalidation. |
| `tests/test_acr_indicators.py` | 18 test untuk primitives. |
| `tests/test_acr_plus_strategy.py` | 6 test integrasi strategy. |
| `tests/test_acr_position_manager.py` | 11 test state machine. |

## Alur Sinyal Entry

Fungsi `evaluate` menerima `ACRPlusContext(htf, ltf, symbol, ...)` dan
melewatkan 5 hard-gate berikut sebelum menghasilkan sinyal:

1. **HTF bias** — HTF harus punya minimal 2 swing high & 2 swing low.
   `HH + HL` → `BULLISH`, `LL + LH` → `BEARISH`. Selain itu **HOLD**.
2. **Premium/Discount** — harga LTF saat ini harus berada di zona
   equilibrium yang tepat: **discount** untuk BUY, **premium** untuk SELL.
3. **ACR pattern actionable** — pattern `confirmed`/`expanded` searah bias
   (candle 2 sweep candle 1, close reclaim, candle 3 respect equilibrium).
4. **CISD confluence** — CISD (body break) searah harus ada di LTF.
5. **Displacement FVG** — FVG searah unfilled setelah candle 2 pattern.

Bonus konfluensi: `mss_confirmed`, `opposing_candle_present`.

### Entry Model

3 kandidat entry, pilih yang RR terbaik (default min 2R):

| Model | Entry Level |
|-------|-------------|
| **Model I** (`I_CISD`) | Harga CISD level |
| **Model II** (`II_FVG`) | Midpoint FVG displacement |
| **Model III** (`III_OPPOSING`) | Harga opposing candle Candle 3 |

### Level SL / TP

- **Stop Loss**: wick candle 2 ± buffer (`sl_buffer_pct` default 0.1%).
- **TP1**: fix 2R (`entry ± risk * min_rr`) sesuai ACR+ Notes.
- **TP2**: swing HTF liquidity (swing_high HTF untuk BUY, swing_low untuk SELL).
- **TP3**: extension `tp2 ± risk` atau swing HTF utama.



## Position Management

`update_position(state, ltf_candles, htf_candles=None)` menghasilkan satu
tick evaluasi:

| Action | Trigger |
|--------|---------|
| `EXIT_SL` | Wick candle menembus `current_stop_loss`. |
| `TAKE_PARTIAL` | TP1 (close 40% + SL ke break-even) atau TP2 (close 35% + aktivasi trailing). |
| `MOVE_SL` | Trailing stop bergeser. |
| `EXIT_TP` | TP3 tercapai dan hold gagal. |
| `EXIT_INVALIDATION` | Setelah TP1 muncul CISD atau ACR pattern lawan arah. |
| `HOLD` | Tidak ada perubahan. |

### Trailing Stop

- Long: `swing_low_terakhir * (1 - trail_buffer_pct)`, hanya boleh naik.
- Short: mirror pada swing_high.
- Default `trail_buffer_pct = 0.2%`, `partial_tp1 = 40%`, `partial_tp2 = 35%`.
- Sisa 25% dipakai untuk TP3 atau hold.

### Hold Decision (Skip TP3)

`evaluate_hold(state, ltf_candles, htf_candles)`:

1. `htf_direction` di state harus ada.
2. Belum ada CISD lawan arah (`counter_cisd`).
3. Belum ada ACR pattern actionable lawan arah (`counter_acr_pattern`).
4. Bila `htf_candles` diberikan: bias HTF masih searah.

Bila lolos semua, `should_hold=True` → `update_position` tidak exit di
TP3, malah mempersempit trailing untuk "ride the trend".

## Contoh Integrasi

```python
from app.strategies.acr_plus import ACRPlusContext, evaluate
from app.strategies.acr_position_manager import PositionState, update_position

ctx = ACRPlusContext(htf=htf_candles, ltf=ltf_candles,
                     symbol="BTCUSDT", htf_tf="H4", ltf_tf="M15")
decision = evaluate(ctx, min_rr=2.0)

if decision.action == "BUY":
    state = PositionState(
        symbol=decision.symbol, side="LONG",
        entry=decision.entry,
        initial_stop_loss=decision.stop_loss,
        current_stop_loss=decision.stop_loss,
        take_profit_1=decision.take_profit_1,
        take_profit_2=decision.take_profit_2,
        take_profit_3=decision.take_profit_3,
        quantity=position_size,
        htf_direction=decision.htf_bias.direction,
    )

update = update_position(state, new_ltf, htf_candles=new_htf)
if update.action.startswith("EXIT"):
    ...  # close position
state = update.next_state
```

## Testing

```bash
./.venv/bin/python -m pytest tests/test_acr_indicators.py \
                              tests/test_acr_plus_strategy.py \
                              tests/test_acr_position_manager.py -v
```

Semua **35 test lulus** dan tidak break test suite lain.

## Integrasi Opsi C (Filter/Konfirmasi)

Modul ACR+ **berjalan paralel** dengan strategi existing (weighted rule engine
+ liquidity_sr_mtf) sebagai **filter/konfirmator** terakhir. Tidak
menggantikan, tapi menambah validasi confluence.

### Modul Bridge

| File | Fungsi |
| --- | --- |
| `app/strategies/acr_confirmation.py` | `confirm_signal()` & `enrich_trading_signal()` — bungkus sinyal dari engine lama dengan konfirmasi ACR+ (align / neutral / conflict + veto). |
| `app/strategies/acr_engine_bridge.py` | `apply_acr_breakeven()`, `apply_acr_trailing()`, `check_acr_invalidation()` — helper untuk position dict di `RealtimePaperTradingEngine`. |

### Cara Aktivasi di Paper Engine

Tambahkan flag di `configs/paper_trading.json`:

```json
{
  "auto_exit": {
    "enabled": true,
    "use_acr_position_manager": true,
    "acr_trail_buffer_pct": 0.002
  }
}
```

Signal yang dikirim ke engine harus menyertakan key `ltf_candles` (list of dict
`{open, high, low, close, timestamp, volume}`) agar bridge bisa menghitung
swing trailing. Bila tidak ada, engine otomatis fallback ke ATR-based logic.

### Cara Enrich Signal Sebelum Eksekusi

```python
from app.signals.builder import build_signal
from app.strategies.acr_confirmation import enrich_trading_signal

signal = build_signal(symbol, ltf_candles, score)   # engine lama
enriched, confirmation = enrich_trading_signal(
    signal,
    htf_candles=htf_candles,
    ltf_candles=ltf_candles,
    veto_on_conflict=True,     # sinyal lawan arah ACR+ jadi SKIP
    veto_on_neutral=False,     # sinyal ACR+ HOLD tetap lolos
)
if enriched.action == "SKIP":
    return  # veto oleh ACR+
# lanjut kirim `enriched` ke RiskManager -> executor
```

**Semantic Alignment:**

| Alignment | Kondisi | Efek |
|-----------|---------|------|
| `align` | ACR+ hasil searah sinyal (BUY-BUY / SELL-SELL) | Confidence ×1.15, tidak veto |
| `neutral` | ACR+ HOLD (gate ACR+ belum lengkap) | Confidence ×0.85, tidak veto (default) |
| `conflict` | ACR+ lawan arah | Confidence ×0.0 dan `action → SKIP` |

## Referensi PDF (docs/pdf/)

- `ACR - Auden Candle Range (1).pdf` — Candle 1-2-3-4.
- `ACR - CISD.pdf` — body break.
- `ACR - FVG.pdf` — FVG + inverse.
- `ACR - IRL ERL.pdf` — IRL/ERL.
- `ACR - Market Structure.pdf` — MSS vs BOS.
- `ACR - Opposing Candle.pdf` — pivot open.
- `ACR - Premium & Discount.pdf` — 50% equilibrium.
- `ACR - Swing Points.pdf` — 3-candle formation.
- `ACR - Timeframe Alignment & Interval Separator.pdf` — pair HTF-LTF.
- `ACR - Entry Model.pdf` — 3 entry model.
