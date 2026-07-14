# Telegram Trade Reports

Bot otomatis kirim laporan trading ke Telegram setiap kali entry, partial close, atau full close posisi.

## Fitur

- **Entry Report**: Detail posisi baru dibuka (symbol, direction, entry price, size, SL, TP, trailing stop)
- **Partial Close Report**: Laporan saat TP1/TP2 terkena, posisi ditutup sebagian
- **Full Close Report**: Laporan lengkap saat posisi ditutup penuh (SL hit, trailing stop, atau TP3)

## Format Laporan

### Entry Position
```
🟢 ENTRY POSITION

Symbol: BTC/USDT
Direction: LONG
Entry: $45,250.5000
Size: 0.1000
Modal: $4,525.05

Stop Loss: $44,800.0000
Take Profit 1: $46,500.0000
Take Profit 2: $47,500.0000
Take Profit 3: $48,500.0000
Trailing: Inactive

Confidence: 85.50%
Reason: Signal BUY detected
```

### Partial Close
```
🟡 PARTIAL CLOSE

Symbol: BTC/USDT
Direction: LONG
Entry: $45,250.5000
Exit: $46,500.0000
Size Closed: 0.0330
Remaining: 0.0670

Realized P&L: $41.50 (+2.78%)
Reason: Take Profit 1
```

### Full Close
```
🔴 CLOSE POSITION

Symbol: BTC/USDT
Direction: LONG
Entry: $45,250.5000
Exit: $45,100.0000
Size Closed: 0.1000
Modal: $4,525.05

Stop Loss: $44,800.0000
Trailing Stop: $45,100.0000
Trailing Active: Yes

TP1: $46,500.0000 ✅
TP2: $47,500.0000 ✅
TP3: $48,500.0000 ❌

Realized P&L: $-59.25 (-1.31%)
Close Reason: 🟡 Trailing Stop
```

## Konfigurasi

Edit `configs/realtime.json`:

```json
{
  "paper_trading_enabled": true,
  "telegram_enabled": true,
  "scan_config": "configs/market_scan.json",
  "paper_config": "configs/paper_trading.json",
  "interval_seconds": 60
}
```

Set `telegram_enabled: true` untuk aktifkan laporan otomatis.

## Implementasi

### 1. Trade Reporter Module
- `app/telegram/trade_reporter.py`: Format pesan entry/close/partial
- `TradeReporter.format_entry()`: Format laporan entry
- `TradeReporter.format_close()`: Format laporan full close
- `TradeReporter.format_partial_close()`: Format laporan partial close
- `send_trade_report()`: Kirim laporan ke notifier

### 2. Integration
- `RealtimePaperTradingEngine.__init__(config, telegram_notifier)`: Terima notifier
- `RealtimePaperTradingEngine._send_telegram_report(event)`: Kirim laporan otomatis
- `run_realtime.py`: Inject TelegramNotifier ke engine

### 3. Event Flow
```
Signal BUY → Open Position → format_entry() → send()
Price hits TP1 → Partial Close → format_partial_close() → send()
Price hits SL → Full Close → format_close() → send()
```

## Testing

Test manual:
```bash
python test_telegram_reporter.py
```

Output:
```
✅ All tests passed!
Messages in outbox: 3
```

## Alasan Design

1. **Lazy Integration**: Telegram notifier optional, tidak break existing flow
2. **Silent Fail**: Jika Telegram error, trading tetap jalan
3. **Rich Format**: Emoji, currency format, percentage untuk readability
4. **Complete Context**: Setiap laporan standalone, tidak perlu scroll history
5. **Position Direction**: LONG/SHORT explicit, tidak ambiguous

## File Changes

- `app/telegram/trade_reporter.py` (new): Format laporan
- `app/telegram/__init__.py`: Export reporter functions
- `app/paper/realtime_engine.py`: Add telegram_notifier param, call _send_telegram_report
- `run_realtime.py`: Inject TelegramNotifier saat paper_enabled
- `test_telegram_reporter.py` (new): Unit test

## Next Steps

Untuk mengirim ke Telegram API real, ganti `TelegramNotifier.send()` dengan HTTP request ke bot API:

```python
import requests

def send(self, message: str) -> None:
    if not self.enabled:
        return
    
    url = f"https://api.telegram.org/bot{self.token}/sendMessage"
    requests.post(url, json={
        "chat_id": self.chat_id,
        "text": message,
        "parse_mode": "Markdown"
    })
```

Tambah `telegram_bot_token` dan `telegram_chat_id` di config.
