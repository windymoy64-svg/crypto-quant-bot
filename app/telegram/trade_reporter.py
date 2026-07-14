from __future__ import annotations

from pathlib import Path
from typing import Any


class TradeReporter:
    """Format trade reports for Telegram notification"""

    def format_entry(self, position: dict[str, Any], signal: dict[str, Any] | None = None) -> str:
        """Format position entry notification dengan signal reasoning"""
        sym = position.get("symbol", "UNKNOWN")
        side = position.get("side", "BUY")
        entry = float(position.get("entry", 0))
        size = float(position.get("remaining_size", position.get("size", 0)))
        sl = float(position.get("stop_loss", 0))
        tp_list = position.get("take_profit", [])
        tp1 = float(tp_list[0]) if tp_list else 0
        tp2 = float(tp_list[1]) if len(tp_list) > 1 else 0
        tp3 = float(tp_list[2]) if len(tp_list) > 2 else 0
        conf = float(position.get("confidence", 0))
        modal = entry * size

        # Extract signal reasoning
        signal = signal or {}
        score = float(signal.get("score", 0))
        risk_reward = float(signal.get("risk_reward", 0))
        strategy = str(signal.get("strategy", "Signal Engine"))
        meta = signal.get("meta", {})
        
        # Extract technical indicators from meta
        reason_parts = []
        if isinstance(meta, dict):
            # MA Crossover
            if "ma5" in meta and "ma20" in meta:
                ma5 = float(meta.get("ma5", 0))
                ma20 = float(meta.get("ma20", 0))
                tf = meta.get("timeframe", "15m")
                if ma5 > ma20:
                    reason_parts.append(f"MA5 ({ma5:.2f}) > MA20 ({ma20:.2f}) [{tf}]")
                else:
                    reason_parts.append(f"MA5 ({ma5:.2f}) < MA20 ({ma20:.2f}) [{tf}]")
            
            # Volume
            if "volume" in meta or "volume_signal" in meta:
                vol = meta.get("volume_signal", meta.get("volume", "normal"))
                reason_parts.append(f"Volume: {vol}")
            
            # RSI
            if "rsi" in meta:
                rsi = float(meta.get("rsi", 0))
                rsi_status = "Oversold" if rsi < 30 else "Overbought" if rsi > 70 else "Neutral"
                reason_parts.append(f"RSI: {rsi:.1f} ({rsi_status})")
            
            # MACD
            if "macd" in meta and "macd_signal" in meta:
                macd = float(meta.get("macd", 0))
                signal_line = float(meta.get("macd_signal", 0))
                macd_status = "Bullish" if macd > signal_line else "Bearish"
                reason_parts.append(f"MACD: {macd_status}")
            
            # Stochastic
            if "stoch_k" in meta and "stoch_d" in meta:
                k = float(meta.get("stoch_k", 0))
                d = float(meta.get("stoch_d", 0))
                stoch_status = "Oversold" if k < 20 else "Overbought" if k > 80 else "Neutral"
                reason_parts.append(f"Stochastic: {k:.1f}/{d:.1f} ({stoch_status})")
            
            # Support/Resistance
            if "support" in meta or "resistance" in meta:
                support = meta.get("support")
                resistance = meta.get("resistance")
                if support and resistance:
                    reason_parts.append(f"S/R: {float(support):.2f}/{float(resistance):.2f}")
            
            # Trend
            if "trend" in meta:
                trend = str(meta.get("trend", "")).upper()
                reason_parts.append(f"Trend: {trend}")
            
            # Rules fired
            if "rules_fired" in meta:
                rules = meta.get("rules_fired", [])
                if isinstance(rules, list) and rules:
                    top_rules = rules[:2]  # Show top 2 rules
                    reason_parts.append(f"Rules: {', '.join(top_rules)}")

        reason_text = " | ".join(reason_parts) if reason_parts else "Signal BUY detected"

        msg = f"""🟢 ENTRY POSITION

Symbol: {sym}
Direction: {"LONG" if side == "BUY" else "SHORT"}
Entry: ${entry:,.4f}
Size: {size:,.4f}
Modal: ${modal:,.2f}

Stop Loss: ${sl:,.4f}
Take Profit 1: ${tp1:,.4f}
Take Profit 2: ${tp2:,.4f}
Take Profit 3: ${tp3:,.4f}
Trailing: Inactive

Score: {score:.0f} | RR: {risk_reward:.1f}:1
Confidence: {conf:.2f}%
Strategy: {strategy}

Reason:
{reason_text}
"""
        return msg.strip()

    def format_close(self, position: dict[str, Any]) -> str:
        """Format position close notification"""
        sym = position.get("symbol", "UNKNOWN")
        side = position.get("side", "BUY")
        entry = float(position.get("entry", 0))
        exit_price = float(position.get("exit", position.get("last_price", 0)))
        size = float(position.get("size", 0))
        remaining = float(position.get("remaining_size", 0))
        closed_size = size - remaining if remaining < size else float(position.get("final_size_closed", size))
        
        sl = float(position.get("static_stop_loss", position.get("stop_loss", 0)))
        trailing_sl = position.get("trailing_stop_loss")
        trailing_active = position.get("trailing_active", False)
        
        tp_list = position.get("take_profit", [])
        tp_hit = position.get("tp_hit", [False, False, False])
        
        pnl = float(position.get("realized_pnl", position.get("final_realized_pnl", 0)))
        modal = entry * closed_size
        pnl_pct = (pnl / modal * 100) if modal > 0 else 0
        
        reason = position.get("close_reason", position.get("reason", "unknown"))
        
        # Determine reason label
        reason_map = {
            "stop_loss": "🔴 Stop Loss Hit",
            "trailing_stop": "🟡 Trailing Stop",
            "take_profit_1": "🟢 Take Profit 1",
            "take_profit_2": "🟢 Take Profit 2", 
            "take_profit_3": "🟢 Take Profit 3",
        }
        reason_label = reason_map.get(reason, f"⚪ {reason}")
        
        icon = "🟢" if pnl >= 0 else "🔴"
        
        tp_status = []
        for i, tp_val in enumerate(tp_list[:3]):
            hit = tp_hit[i] if i < len(tp_hit) else False
            tp_status.append(f"TP{i+1}: ${float(tp_val):,.4f} {'✅' if hit else '❌'}")
        
        trailing_text = f"${float(trailing_sl):,.4f}" if trailing_sl else "Inactive"

        msg = f"""
{icon} CLOSE POSITION

Symbol: {sym}
Direction: {"LONG" if side == "BUY" else "SHORT"}
Entry: ${entry:,.4f}
Exit: ${exit_price:,.4f}
Size Closed: {closed_size:,.4f}
Modal: ${modal:,.2f}

Stop Loss: ${sl:,.4f}
Trailing Stop: {trailing_text}
Trailing Active: {'Yes' if trailing_active else 'No'}

{chr(10).join(tp_status)}

Realized P&L: ${pnl:,.2f} ({pnl_pct:+.2f}%)
Close Reason: {reason_label}
"""
        return msg.strip()

    def format_partial_close(self, position: dict[str, Any]) -> str:
        """Format partial close notification"""
        sym = position.get("symbol", "UNKNOWN")
        side = position.get("side", "BUY")
        entry = float(position.get("entry", 0))
        exit_price = float(position.get("partial_exit_price", position.get("last_price", 0)))
        partial_size = float(position.get("partial_size_closed", 0))
        remaining = float(position.get("remaining_size", 0))
        
        partial_pnl = float(position.get("partial_realized_pnl", 0))
        modal = entry * partial_size
        pnl_pct = (partial_pnl / modal * 100) if modal > 0 else 0
        
        reason = position.get("partial_reason", "unknown")
        icon = "🟢" if partial_pnl >= 0 else "🔴"
        
        msg = f"""
🟡 PARTIAL CLOSE

Symbol: {sym}
Direction: {"LONG" if side == "BUY" else "SHORT"}
Entry: ${entry:,.4f}
Exit: ${exit_price:,.4f}
Size Closed: {partial_size:,.4f}
Remaining: {remaining:,.4f}

Realized P&L: ${partial_pnl:,.2f} ({pnl_pct:+.2f}%)
Reason: {reason.replace('_', ' ').title()}
"""
        return msg.strip()


def send_trade_report(notifier: Any, trade_event: dict[str, Any]) -> None:
    """Send trade report via Telegram notifier"""
    reporter = TradeReporter()
    event_type = trade_event.get("type", "")
    position = trade_event.get("position")
    signal = trade_event.get("signal")
    
    if not position:
        return
    
    if event_type == "opened":
        msg = reporter.format_entry(position, signal)
    elif event_type == "closed":
        msg = reporter.format_close(position)
    elif event_type == "partial_close":
        msg = reporter.format_partial_close(position)
    else:
        return
    
    notifier.send(msg)
