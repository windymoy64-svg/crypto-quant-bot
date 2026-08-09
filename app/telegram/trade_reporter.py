from __future__ import annotations

from pathlib import Path
from typing import Any
from html import escape


class TradeReporter:
    """Format trade reports for Telegram notification"""

    def format_live_execution(self, decision: dict[str, Any], execution: dict[str, Any]) -> str:
        """Format the live execution result in the operational alert layout."""
        action = str(decision.get("action") or "ENTRY").upper()
        symbol = escape(str(decision.get("symbol") or execution.get("symbol") or "UNKNOWN"))
        side = "SHORT" if action.endswith("SELL") else "LONG"
        plan = decision.get("entry_plan") if isinstance(decision.get("entry_plan"), dict) else {}
        entry = float(plan.get("entry_price") or 0)
        stop = float(plan.get("stop_loss") or 0)
        tp1 = float(plan.get("take_profit_1") or 0)
        score = float(decision.get("confidence_score") or 0)
        confluence = float(decision.get("confluence_score") or 0)
        regime = escape(str(decision.get("regime") or "UNKNOWN"))
        reasons = decision.get("reasons") if isinstance(decision.get("reasons"), list) else []
        thesis = escape(", ".join(str(reason) for reason in reasons if str(reason).strip()) or "signal accepted")
        results = execution.get("results") if isinstance(execution.get("results"), list) else []
        result = next(
            (
                item for item in results
                if isinstance(item, dict)
                and str((item.get("meta") or {}).get("role", "")).lower() == "entry"
            ),
            next((item for item in results if isinstance(item, dict)), {}),
        )
        raw_status = str(result.get("status") or "").upper()
        status_value = raw_status or ("FILLED" if execution.get("success") else "REJECTED")
        rejected = status_value == "REJECTED"
        protection_failed = "live_entry_take_profit_not_confirmed" in {
            str(error) for error in (execution.get("errors") or [])
        }
        submitted = status_value in {"SUBMITTED", "PENDING", "NEW", "INIT"}
        if protection_failed:
            title, icon = "LIVE ENTRY PROTECTION FAILED", "🚨"
        elif rejected:
            title, icon = "LIVE ORDER REJECTED", "❌"
        elif submitted:
            title, icon = "LIVE ENTRY SUBMITTED", "🟡"
        else:
            title, icon = "LIVE ENTRY EXECUTED", "✅"
        status = escape(status_value)
        quantity = float(result.get("filled_quantity") or result.get("requested_quantity") or 0)
        notional = entry * quantity
        exchange_reason = str(
            result.get("reason")
            or ("exchange rejected" if rejected else "exchange accepted")
        )
        order_id = escape(str(result.get("order_id") or "-"))
        return (
            f"{icon} {title}\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"{symbol}  •  {side}\n"
            f"Status: {status}\n\n"
            f"💵 Entry: ${entry:,.6f}\n"
            f"📦 Quantity: {quantity:,.8f}\n"
            f"💰 Notional: ${notional:,.2f}\n"
            f"🛡 Stop Loss: ${stop:,.6f}\n"
            f"🎯 TP1: ${tp1:,.6f}\n\n"
            f"📊 Score: {score:.1f}  •  Confluence: {confluence:.1f}\n"
            f"🌐 Regime: {regime}\n"
            f"🧠 Thesis: {thesis}\n\n"
            f"📝 Exchange: {escape(exchange_reason)}\n"
            f"🆔 Order: {order_id}\n"
            "🏦 Venue: Bitunix Futures"
        )

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

        # Prefer the precomputed entry reason stored on the position by the
        # engine (score, RR, and passed rule names). Fall back to any meta the
        # signal happens to carry, then to a generic label.
        entry_reason = str(position.get("entry_reason", "")).strip()
        if entry_reason:
            reason_text = entry_reason
        elif reason_parts:
            reason_text = " | ".join(reason_parts)
        else:
            reason_text = "Signal BUY detected"

        msg = f"""🟢 ENTRY POSITION
━━━━━━━━━━━━━━━━━━

{sym}  •  {"LONG" if side == "BUY" else "SHORT"}
Status: FILLED

💵 Entry: ${entry:,.6f}
📦 Quantity: {size:,.8f}
💰 Notional: ${modal:,.2f}

🛡 Stop Loss: ${sl:,.6f}
🎯 TP1: ${tp1:,.6f}

📊 Score: {score:.1f}  •  Confidence: {conf:.1f}
🧠 Thesis: {reason_text}

🏦 Venue: Paper Trading
"""
        return msg.strip()

    def format_close(self, position: dict[str, Any], *, venue: str = "Paper Trading") -> str:
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
        entry_reason = str(position.get("entry_reason", "")).strip()
        
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
━━━━━━━━━━━━━━━━━━

{sym}  •  {"LONG" if side == "BUY" else "SHORT"}
Status: CLOSED

💵 Entry: ${entry:,.6f}
🚪 Exit: ${exit_price:,.6f}
📦 Quantity: {closed_size:,.8f}
💰 Notional: ${modal:,.2f}

🛡 Stop Loss: ${sl:,.6f}
🎯 TP1: ${float(tp_list[0]) if tp_list else 0:,.6f}

📈 Realized P&L: ${pnl:,.2f} ({pnl_pct:+.2f}%)
📝 Reason: {reason_label}
🏦 Venue: {venue}
"""
        return msg.strip()

    def format_partial_close(self, position: dict[str, Any], *, venue: str = "Paper Trading") -> str:
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
━━━━━━━━━━━━━━━━━━

{sym}  •  {"LONG" if side == "BUY" else "SHORT"}
Status: PARTIAL

💵 Entry: ${entry:,.6f}
🚪 Exit: ${exit_price:,.6f}
📦 Closed: {partial_size:,.8f}
📦 Remaining: {remaining:,.8f}

📈 Realized P&L: ${partial_pnl:,.2f} ({pnl_pct:+.2f}%)
📝 Reason: {reason.replace('_', ' ').title()}
🏦 Venue: {venue}
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
