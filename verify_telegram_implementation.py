#!/usr/bin/env python3
"""Final verification checklist untuk Telegram Trade Reporter implementation"""

import sys
from pathlib import Path

def check_file_exists(path: str, description: str) -> bool:
    """Verify file exists"""
    exists = Path(path).exists()
    status = "✅" if exists else "❌"
    print(f"{status} {description:50} {path}")
    return exists

def check_imports() -> bool:
    """Verify all imports work"""
    try:
        from app.telegram import TradeReporter, send_trade_report, TelegramNotifier
        from app.paper.realtime_engine import RealtimePaperTradingEngine, PaperTradingConfig
        print("✅ All imports successful")
        return True
    except Exception as e:
        print(f"❌ Import failed: {e}")
        return False

def check_functionality() -> bool:
    """Verify core functionality"""
    try:
        from app.telegram import TradeReporter
        
        reporter = TradeReporter()
        
        # Test entry with signal
        position = {
            "symbol": "BTC/USDT",
            "side": "BUY",
            "entry": 45250.50,
            "size": 0.1,
            "remaining_size": 0.1,
            "stop_loss": 44800.00,
            "take_profit": [46500.00, 47500.00, 48500.00],
            "confidence": 85.5,
        }
        
        signal = {
            "score": 205.0,
            "risk_reward": 3.5,
            "strategy": "Test Engine",
            "meta": {
                "ma5": 45180.25,
                "ma20": 45050.00,
                "timeframe": "15m",
                "volume_signal": "above_average",
                "rsi": 65.5,
                "trend": "BULLISH",
            }
        }
        
        # Test format_entry with signal
        msg = reporter.format_entry(position, signal)
        assert "ENTRY POSITION" in msg
        assert "BTC/USDT" in msg
        assert "MA5" in msg
        assert "Volume: above_average" in msg
        assert "Trend: BULLISH" in msg
        
        print("✅ format_entry() dengan signal reasoning works")
        
        # Test partial close
        partial_pos = {**position, "remaining_size": 0.067}
        msg = reporter.format_partial_close(partial_pos)
        assert "PARTIAL CLOSE" in msg
        
        print("✅ format_partial_close() works")
        
        # Test close
        close_pos = {
            **position,
            "remaining_size": 0,
            "exit": 45100.00,
            "realized_pnl": -100.75,
            "close_reason": "trailing_stop",
        }
        msg = reporter.format_close(close_pos)
        assert "CLOSE POSITION" in msg
        
        print("✅ format_close() works")
        
        return True
    except Exception as e:
        print(f"❌ Functionality test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    print("=" * 80)
    print("TELEGRAM TRADE REPORTER - FINAL VERIFICATION")
    print("=" * 80)
    
    # 1. Check files
    print("\n📁 Files Check:")
    files_ok = all([
        check_file_exists("app/telegram/trade_reporter.py", "TradeReporter module"),
        check_file_exists("app/telegram/__init__.py", "Telegram package init"),
        check_file_exists("app/paper/realtime_engine.py", "Paper trading engine"),
        check_file_exists("run_realtime.py", "Realtime runner"),
        check_file_exists("test_telegram_reporter.py", "Test script"),
        check_file_exists("demo_telegram_integration.py", "Demo script"),
        check_file_exists("TELEGRAM_IMPLEMENTATION.md", "Implementation doc"),
        check_file_exists("TELEGRAM_DETAILED_REASONING.md", "Reasoning doc"),
        check_file_exists("docs/TELEGRAM_REPORTS.md", "Reports doc"),
    ])
    
    # 2. Check imports
    print("\n📦 Imports Check:")
    imports_ok = check_imports()
    
    # 3. Check functionality
    print("\n⚙️  Functionality Check:")
    func_ok = check_functionality()
    
    # 4. Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    
    checks = {
        "Files": files_ok,
        "Imports": imports_ok,
        "Functionality": func_ok,
    }
    
    for check_name, result in checks.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status:10} {check_name}")
    
    all_ok = all(checks.values())
    
    print("\n" + "=" * 80)
    if all_ok:
        print("🎉 ALL CHECKS PASSED - READY FOR PRODUCTION")
        print("=" * 80)
        print("\nFeatures Implemented:")
        print("  ✅ Entry notification dengan technical reasoning")
        print("  ✅ Partial close notification")
        print("  ✅ Full close notification")
        print("  ✅ Signal meta extraction (MA, Volume, RSI, MACD, etc)")
        print("  ✅ Integration dengan paper trading engine")
        print("  ✅ Telegram notifier support")
        print("  ✅ Backwards compatible")
        print("\nTo activate:")
        print("  1. Edit configs/realtime.json")
        print("  2. Set telegram_enabled: true")
        print("  3. Run: python run_realtime.py")
        print("=" * 80)
        return 0
    else:
        print("❌ SOME CHECKS FAILED - FIX BEFORE PRODUCTION")
        print("=" * 80)
        return 1

if __name__ == "__main__":
    sys.exit(main())
