from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Protocol

from app.live.account import AccountSnapshot, OpenOrderSummary
from app.live.account_validator import AccountPreflightValidator
from app.live.config import LiveConfig
from app.live.models import LiveOrder


@dataclass(frozen=True)
class PreflightResult:
    approved: bool
    reason: str
    account_snapshot: AccountSnapshot | None = None
    open_orders: list[OpenOrderSummary] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["account_snapshot"] = self.account_snapshot.to_dict() if self.account_snapshot else None
        data["open_orders"] = [order.to_dict() for order in self.open_orders]
        return data


class AccountPreflightReader(Protocol):
    def account_snapshot(self) -> AccountSnapshot:
        ...

    def open_orders(self, symbol: str | None = None) -> list[OpenOrderSummary]:
        ...


class AccountPreflightEngine:
    def __init__(
        self,
        reader: AccountPreflightReader,
        config: LiveConfig | None = None,
        *,
        validator: AccountPreflightValidator | None = None,
    ) -> None:
        self.reader = reader
        self.config = config or LiveConfig()
        self.validator = validator or AccountPreflightValidator(self.config)

    def validate(self, order: LiveOrder, *, daily_orders: int = 0, exchange_validated: bool = True) -> PreflightResult:
        try:
            snapshot = self.reader.account_snapshot()
            open_orders = self.reader.open_orders(order.symbol)
        except Exception as exc:  # pragma: no cover - exact connector exceptions vary by environment.
            return PreflightResult(False, f"account_api_key_invalid_or_unavailable:{exc.__class__.__name__}")

        return self.validator.validate(
            order=order,
            account_snapshot=snapshot,
            open_orders=open_orders,
            daily_orders=daily_orders,
            exchange_validated=exchange_validated,
        )