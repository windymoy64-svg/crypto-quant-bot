from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.analytics.statistics import safe_float


@dataclass(frozen=True)
class TradeJournalEntry:
    source: str
    symbol: str
    side: str
    quantity: float
    entry_time: str
    exit_time: str
    entry_price: float
    exit_price: float
    gross_pnl: float
    fees: float
    net_pnl: float
    return_percent: float
    exit_reason: str = ""
    regime: str = "unknown"
    pair: str = ""
    rules: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def is_win(self) -> bool:
        return self.net_pnl > 0

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class TradeJournal:
    def __init__(self, entries: list[TradeJournalEntry] | None = None) -> None:
        self.entries = entries or []

    def add(self, entry: TradeJournalEntry) -> None:
        self.entries.append(entry)

    def extend(self, entries: list[TradeJournalEntry]) -> None:
        self.entries.extend(entries)

    def to_dict(self) -> dict[str, object]:
        return {
            "trades": [entry.to_dict() for entry in self.entries],
            "count": len(self.entries),
        }

    @classmethod
    def from_backtest_trades(cls, trades: list[dict[str, object]], source: str = "backtest") -> "TradeJournal":
        journal = cls()
        for trade in trades:
            symbol = str(trade.get("symbol", ""))
            journal.add(
                TradeJournalEntry(
                    source=source,
                    symbol=symbol,
                    side=str(trade.get("entry_side", "BUY")),
                    quantity=safe_float(trade.get("quantity")),
                    entry_time=str(trade.get("entry_time", "")),
                    exit_time=str(trade.get("exit_time", "")),
                    entry_price=safe_float(trade.get("entry_price")),
                    exit_price=safe_float(trade.get("exit_price")),
                    gross_pnl=safe_float(trade.get("gross_pnl")),
                    fees=safe_float(trade.get("fees")),
                    net_pnl=safe_float(trade.get("net_pnl")),
                    return_percent=safe_float(trade.get("return_percent")),
                    exit_reason=str(trade.get("exit_reason", "")),
                    regime=str(trade.get("regime", trade.get("market_regime", "unknown"))),
                    pair=symbol,
                    rules=_rules_from_meta(trade.get("meta")),
                    meta={"raw": trade},
                )
            )
        return journal

    @classmethod
    def from_paper_fills(cls, fills: list[dict[str, object]], source: str = "paper") -> "TradeJournal":
        journal = cls()
        open_lots: dict[str, list[dict[str, object]]] = {}
        for fill in sorted(fills, key=lambda item: str(item.get("timestamp", ""))):
            symbol = str(fill.get("symbol", ""))
            side = str(fill.get("side", "")).upper()
            quantity = safe_float(fill.get("quantity"))
            price = safe_float(fill.get("price"))
            fee = safe_float(fill.get("fee"))
            timestamp = str(fill.get("timestamp", ""))
            if quantity <= 0 or price <= 0:
                continue
            if side == "BUY":
                open_lots.setdefault(symbol, []).append({
                    "quantity": quantity,
                    "price": price,
                    "fee": fee,
                    "timestamp": timestamp,
                })
                continue
            if side != "SELL":
                continue

            remaining = quantity
            lots = open_lots.setdefault(symbol, [])
            while remaining > 0 and lots:
                lot = lots[0]
                lot_quantity = safe_float(lot.get("quantity"))
                matched = min(remaining, lot_quantity)
                if matched <= 0:
                    lots.pop(0)
                    continue

                entry_price = safe_float(lot.get("price"))
                entry_fee = safe_float(lot.get("fee")) * (matched / lot_quantity) if lot_quantity else 0.0
                exit_fee = fee * (matched / quantity) if quantity else 0.0
                gross_pnl = (price - entry_price) * matched
                total_fees = entry_fee + exit_fee
                net_pnl = gross_pnl - total_fees
                cost_basis = entry_price * matched
                return_percent = (net_pnl / cost_basis) * 100 if cost_basis else 0.0
                journal.add(
                    TradeJournalEntry(
                        source=source,
                        symbol=symbol,
                        side="BUY",
                        quantity=round(matched, 8),
                        entry_time=str(lot.get("timestamp", "")),
                        exit_time=timestamp,
                        entry_price=round(entry_price, 8),
                        exit_price=round(price, 8),
                        gross_pnl=round(gross_pnl, 8),
                        fees=round(total_fees, 8),
                        net_pnl=round(net_pnl, 8),
                        return_percent=round(return_percent, 4),
                        exit_reason=str(fill.get("reason", "")),
                        pair=symbol,
                        meta={"entry_fill": lot, "exit_fill": fill},
                    )
                )
                lot["quantity"] = round(lot_quantity - matched, 8)
                remaining = round(remaining - matched, 8)
                if safe_float(lot.get("quantity")) <= 0:
                    lots.pop(0)
        return journal


def _rules_from_meta(meta: object) -> list[str]:
    if not isinstance(meta, dict):
        return []
    rules = meta.get("rules") or meta.get("passed_rules") or meta.get("failed_rules") or []
    if not isinstance(rules, list):
        return []
    return [str(rule) for rule in rules]