from __future__ import annotations

from dataclasses import dataclass

from app.portfolio.account import PortfolioAccount

from app.portfolio.balance import AccountBalance


@dataclass(frozen=True)
class PaperAccountSnapshot:
    initial_balance: float
    cash: float
    realized_pnl: float = 0.0

    @classmethod
    def from_dict(cls, data: dict[str, object], default_balance: float) -> "PaperAccountSnapshot":
        return cls(
            initial_balance=float(data.get("initial_balance", default_balance)),
            cash=float(data.get("cash", default_balance)),
            realized_pnl=float(data.get("realized_pnl", 0.0)),
        )

    @classmethod
    def from_portfolio(cls, account: PortfolioAccount) -> "PaperAccountSnapshot":
        return cls(
            initial_balance=account.balance.initial_balance,
            cash=account.balance.cash,
            realized_pnl=account.balance.realized_pnl,
        )

    def to_portfolio_account(self) -> PortfolioAccount:
        return PortfolioAccount(
            AccountBalance(
                initial_balance=self.initial_balance,
                cash=self.cash,
                realized_pnl=self.realized_pnl,
            )
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "initial_balance": round(self.initial_balance, 8),
            "cash": round(self.cash, 8),
            "realized_pnl": round(self.realized_pnl, 8),
            "available_balance": round(max(self.cash, 0.0), 8),
        }