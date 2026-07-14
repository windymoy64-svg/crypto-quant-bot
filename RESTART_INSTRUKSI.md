# Manual Restart Bot - Sistem TP/SL/Trailing Baru

## Perubahan yang Diterapkan

### 1. Stop Loss (Structure-based)
- **LONG**: SL di bawah swing low terdekat + buffer 0.5×ATR
- **SHORT**: SL di atas swing high terdekat + buffer 0.5×ATR
- **Fallback**: ATR 1.5× jika struktur tidak ditemukan

### 2. Take Profit (Resistance/Support-based)
- **TP1**: Resistance/support terdekat, minimum 2R (RR ≥ 1:2)
- **TP2**: TP1 + 1.5×ATR
- **TP3**: TP1 + 3.0×ATR

### 3. Break-even on TP1
- Setelah TP1 hit (30% closed) → SL otomatis geser ke entry price
- Trade jadi risk-free, sisa 70% posisi dibiarkan jalan

### 4. Trailing Stop
- Aktif setelah TP1 hit
- Distance: 1.5×ATR dari highest/lowest price
- Floor: tidak boleh di bawah entry (breakeven minimum)

---

## Cara Manual Restart Bot

```bash
# 1. Masuk ke folder bot
cd /opt/crypto-quant-bot

# 2. Stop semua process
pkill -f run_realtime
pkill -f run_live
# atau
killall python3

# 3. Tunggu 2-3 detik
sleep 3

# 4. Cek state (opsional)
cat logs/paper_state.json | python -m json.tool | head -50

# 5. Start ulang bot
nohup python run_realtime.py >> logs/bot.log 2>&1 &

# 6. Cek log
tail -f logs/bot.log

# Atau pakai systemd (jika ada):
systemctl restart crypto-quant-bot
systemctl status crypto-quant-bot
```

---

## Verifikasi Sistem Baru Berjalan

Cek log untuk melihat signal baru dengan struktur:

```bash
tail -100 logs/signals.jsonl | grep -E "stop_loss|take_profit"
```

Atau cek latest signals:

```bash
cat logs/latest_signals.json | python -m json.tool
```

Cari field:
- `stop_loss` — harusnya tidak lagi pure ATR, tapi struktur + buffer
- `take_profit` — array [TP1, TP2, TP3] dengan TP1 berbasis resistance/support
- `risk_reward` — minimal 2.0

---

## File yang Diubah

1. **app/indicators/structure.py** (BARU)
   - `find_swing_low()`, `find_swing_high()`
   - `find_nearest_resistance()`, `find_nearest_support()`

2. **app/signals/builder.py**
   - `build_signal()` — SL/TP logic untuk LONG
   - `build_short_signal()` — SL/TP logic untuk SHORT

3. **app/paper/realtime_engine.py**
   - `_process_take_profits()` — tambah break-even on TP1

---

## Posisi yang Sudah Terbuka

Posisi lama tetap pakai SL/TP lama. Sistem baru hanya berlaku untuk **posisi baru** setelah restart.

Jika ingin update posisi lama:
- Close manual lewat dashboard
- Atau edit `logs/paper_state.json` (HATI-HATI, backup dulu)

---

## Troubleshooting

**Bot tidak start:**
```bash
# Cek error
cat logs/bot.log

# Test import
python -c "from app.signals.builder import build_signal; print('OK')"
python -c "from app.indicators.structure import find_swing_low; print('OK')"
```

**SL terlalu jauh:**
- Normal jika swing structure jauh dari entry
- Position size akan mengecil otomatis (risk % tetap)
- Atau fallback ke ATR jika struktur > 10% dari entry

**TP tidak muncul:**
- Cek apakah ada resistance/support dalam 30 candles terakhir
- Fallback ke 2R jika tidak ada struktur

---

## Monitoring

Dashboard: http://localhost:8080 (atau VPS IP)

Telegram: Notifikasi otomatis saat open/close position

Logs:
- `logs/bot.log` — runtime log
- `logs/paper_trades.jsonl` — trade events
- `logs/signals.jsonl` — signal history
- `logs/paper_state.json` — current state

---

**Sistem sudah siap. Tinggal restart manual sesuai instruksi di atas.**
