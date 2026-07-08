from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class AccountBalance:
    initial_balance: float
    cash: float
    realized_pnl: float = 0.0

    @property
    def available_balance(self) -> float:
        return max(self.cash, 0.0)

    def reserve(self, amount: float) -> None:
        self.cash -= max(amount, 0.0)

    def release(self, amount: float) -> None:
        self.cash += max(amount, 0.0)

    def add_realized_pnl(self, pnl: float) -> None:
        self.realized_pnl += pnl

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["available_balance"] = round(self.available_balance, 8)
        return data