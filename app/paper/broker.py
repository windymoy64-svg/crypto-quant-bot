from __future__ import annotations

from app.core.models import TradingSignal
from app.risk.manager import calculate_position_size


class PaperBroker:
    def __init__(self, balance: float = 10_000.0, risk_percent: float = 1.0) -> None:
        self.balance = balance
        self.risk_percent = risk_percent
        self.positions: list[dict[str, float | str]] = []

    def execute(self, signal: TradingSignal) -> dict[str, float | str]:
        if signal.action != "BUY":
            return {"status": "ignored", "reason": f"action={signal.action}"}

        size = calculate_position_size(
            account_balance=self.balance,
            risk_percent=self.risk_percent,
            entry=signal.entry,
            stop_loss=signal.stop_loss,
        )
        position = {
            "status": "opened",
            "symbol": signal.symbol,
            "side": "BUY",
            "entry": signal.entry,
            "size": size,
            "stop_loss": signal.stop_loss,
            "take_profit_1": signal.take_profit[0],
        }
        self.positions.append(position)
        return position
