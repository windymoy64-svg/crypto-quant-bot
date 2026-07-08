from __future__ import annotations

from dataclasses import dataclass

from app.portfolio.balance import AccountBalance


@dataclass
class PortfolioAccount:
    balance: AccountBalance

    @classmethod
    def with_cash(cls, initial_balance: float) -> "PortfolioAccount":
        return cls(AccountBalance(initial_balance=initial_balance, cash=initial_balance))

    @property
    def cash(self) -> float:
        return self.balance.cash

    @property
    def available_balance(self) -> float:
        return self.balance.available_balance

    @property
    def realized_pnl(self) -> float:
        return self.balance.realized_pnl

    def to_dict(self) -> dict[str, object]:
        return self.balance.to_dict()