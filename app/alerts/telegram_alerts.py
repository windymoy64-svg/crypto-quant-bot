from typing import Dict, List

class TelegramAlerts:
    """Send alerts to Telegram"""
    
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
    
    def send_alert(self, result: object) -> bool:
        """Send a trading alert"""
        if not result or not hasattr(result, 'action'):
            return False
        
        # Only send alerts for actionable signals (not SKIP)
        if result.action in ['BUY', 'WATCH']:
            message = self._format_alert_message(result)
            return self._send_telegram_message(message)
        
        return False
    
    def _format_alert_message(self, result: object) -> str:
        """Format a result object into a readable alert message"""
        symbol = getattr(result, 'symbol', 'UNKNOWN')
        action = getattr(result, 'action', 'UNKNOWN')
        score = getattr(result, 'confluence_score', 0)
        timeframe = getattr(result, 'timeframe', '15m')
        reasons = getattr(result, 'reasons', [])
        warnings = getattr(result, 'warnings', [])
        data_quality = getattr(result, 'data_quality', 'UNKNOWN')
        
        message = f"{symbol} — {action}\n"
        message += f"Score: {score:.1f}/100\n"
        message += f"Timeframe: {timeframe}\n"
        message += f"Data Quality: {data_quality}\n\n"
        
        if reasons:
            message += "Reasons:\n"
            for reason in reasons[:5]:  # Limit to top 5 reasons
                message += f"- {reason}\n"
        
        if warnings:
            message += "\nWarnings:\n"
            for warning in warnings[:3]:  # Limit to top 3 warnings
                message += f"- {warning}\n"
        
        return message
    
    def _send_telegram_message(self, message: str) -> bool:
        """Send a message to Telegram"""
        # In production, implement actual Telegram API call
        # For now, this is a placeholder
        print(f"[Telegram] {message}")
        return True