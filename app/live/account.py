from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.exchange.binance.client import BinanceConnector
from app.live.exchange_rules import normalize_symbol


@dataclass(frozen=True)
class AccountSnapshot:
    account_type: str
    can_trade: bool
    can_withdraw: bool
    can_deposit: bool
    maker_commission: int
    taker_commission: int
    buyer_commission: int
    seller_commission: int
    balances: dict[str, dict[str, float]] = field(default_factory=dict)
    permissions: list[str] = field(default_factory=list)
    update_time: int = 0

    @classmethod
    def from_binance(cls, data: dict[str, Any]) -> "AccountSnapshot":
        return cls(
            account_type=str(data.get("accountType", "")),
            can_trade=bool(data.get("canTrade", False)),
            can_withdraw=bool(data.get("canWithdraw", False)),
            can_deposit=bool(data.get("canDeposit", False)),
            maker_commission=int(data.get("makerCommission", 0)),
            taker_commission=int(data.get("takerCommission", 0)),
            buyer_commission=int(data.get("buyerCommission", 0)),
            seller_commission=int(data.get("sellerCommission", 0)),
            balances=cls._parse_balances(data.get("balances", [])),
            permissions=[str(value) for value in data.get("permissions", [])],
            update_time=int(data.get("updateTime", 0)),
        )

    @classmethod
    def _parse_balances(cls, rows: object) -> dict[str, dict[str, float]]:
        balances: dict[str, dict[str, float]] = {}
        if not isinstance(rows, list):
            return balances
        for row in rows:
            if not isinstance(row, dict):
                continue
            asset = str(row.get("asset", "")).upper()
            if not asset:
                continue
            balances[asset] = {
                "free": float(row.get("free") or 0.0),
                "locked": float(row.get("locked") or 0.0),
            }
        return balances

    def free_balance(self, asset: str) -> float:
        return float(self.balances.get(asset.upper(), {}).get("free", 0.0))

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class OpenOrderSummary:
    symbol: str
    side: str
    type: str
    status: str
    orig_qty: float
    executed_qty: float
    price: float

    @classmethod
    def from_binance(cls, data: dict[str, Any]) -> "OpenOrderSummary":
        return cls(
            symbol=normalize_symbol(str(data.get("symbol", ""))),
            side=str(data.get("side", "")),
            type=str(data.get("type", "")),
            status=str(data.get("status", "")),
            orig_qty=float(data.get("origQty") or 0.0),
            executed_qty=float(data.get("executedQty") or 0.0),
            price=float(data.get("price") or 0.0),
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class BinanceAccountPreflightReader:
    def __init__(self, connector: BinanceConnector | None = None) -> None:
        self.connector = connector or BinanceConnector()

    def account_snapshot(self) -> AccountSnapshot:
        return AccountSnapshot.from_binance(self.connector.account.account())

    def open_orders(self, symbol: str | None = None) -> list[OpenOrderSummary]:
        rows = self.connector.account.open_orders(symbol)
        return [OpenOrderSummary.from_binance(row) for row in rows]

    def my_trades(self, symbol: str, limit: int = 50) -> list[dict[str, object]]:
        return self.connector.account.my_trades(symbol, limit=limit)