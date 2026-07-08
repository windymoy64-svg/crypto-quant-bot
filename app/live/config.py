from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class LiveConfig:
    enabled: bool = False
    dry_run: bool = True
    exchange: str = "binance"
    order_type: str = "MARKET"
    default_quote_amount: float = 100.0
    max_daily_orders: int = 10
    confirm_before_live: bool = True
    confirm_live: bool = False
    minimum_quote_balance: float = 100.0
    max_open_orders: int = 5
    require_can_trade: bool = True
    require_spot_permission: bool = True
    cooldown_seconds: int = 300
    max_same_symbol_orders: int = 1

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LiveConfig":
        return cls(
            enabled=bool(data.get("enabled", False)),
            dry_run=bool(data.get("dry_run", True)),
            exchange=str(data.get("exchange", "binance")),
            order_type=str(data.get("order_type", "MARKET")).upper(),
            default_quote_amount=float(data.get("default_quote_amount", 100.0)),
            max_daily_orders=int(data.get("max_daily_orders", 10)),
            confirm_before_live=bool(data.get("confirm_before_live", True)),
            confirm_live=bool(data.get("confirm_live", False)),
            minimum_quote_balance=float(data.get("minimum_quote_balance", 100.0)),
            max_open_orders=int(data.get("max_open_orders", 5)),
            require_can_trade=bool(data.get("require_can_trade", True)),
            require_spot_permission=bool(data.get("require_spot_permission", True)),
            cooldown_seconds=int(data.get("cooldown_seconds", 300)),
            max_same_symbol_orders=int(data.get("max_same_symbol_orders", 1)),
        )

    @classmethod
    def from_json(cls, path: str | Path) -> "LiveConfig":
        target = Path(path)
        if not target.exists():
            return cls()
        return cls.from_dict(json.loads(target.read_text(encoding="utf-8-sig")))

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
