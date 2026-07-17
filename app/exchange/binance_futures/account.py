"""Read-only helpers for the USDⓈ-M Futures account.

Wraps ``GET /fapi/v3/account``, ``GET /fapi/v3/balance``, and
``GET /fapi/v3/positionRisk``. The v3 endpoints are preferred because they
return more accurate wallet/margin figures than the deprecated v2 variants.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.exchange.binance_futures.client import FuturesHttpClient


@dataclass(frozen=True)
class FuturesBalance:
    asset: str
    wallet_balance: float
    available_balance: float
    cross_wallet_balance: float
    cross_unrealized_pnl: float
    max_withdraw_amount: float
    update_time: int


@dataclass(frozen=True)
class FuturesPosition:
    symbol: str
    position_side: str  # "BOTH" (one-way) | "LONG" | "SHORT" (hedge)
    position_amount: float
    entry_price: float
    mark_price: float
    unrealized_profit: float
    leverage: int
    liquidation_price: float
    margin_type: str  # "isolated" | "cross"
    isolated_wallet: float
    update_time: int


@dataclass(frozen=True)
class FuturesAccountSnapshot:
    total_wallet_balance: float
    total_unrealized_profit: float
    total_margin_balance: float
    available_balance: float
    max_withdraw_amount: float
    can_trade: bool
    can_deposit: bool
    can_withdraw: bool
    fee_tier: int
    balances: list[FuturesBalance] = field(default_factory=list)
    positions: list[FuturesPosition] = field(default_factory=list)


def _as_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


class FuturesAccountReader:
    """Read-only view of the USDⓈ-M Futures account."""

    def __init__(self, client: FuturesHttpClient) -> None:
        self._client = client

    def snapshot(self) -> FuturesAccountSnapshot:
        response = self._client.get("/fapi/v3/account")
        payload = response.body if isinstance(response.body, dict) else {}
        balances = [
            _parse_balance(entry)
            for entry in payload.get("assets", [])
            if isinstance(entry, dict)
        ]
        positions = [
            _parse_position(entry)
            for entry in payload.get("positions", [])
            if isinstance(entry, dict)
        ]
        return FuturesAccountSnapshot(
            total_wallet_balance=_as_float(payload.get("totalWalletBalance")),
            total_unrealized_profit=_as_float(payload.get("totalUnrealizedProfit")),
            total_margin_balance=_as_float(payload.get("totalMarginBalance")),
            available_balance=_as_float(payload.get("availableBalance")),
            max_withdraw_amount=_as_float(payload.get("maxWithdrawAmount")),
            can_trade=bool(payload.get("canTrade", False)),
            can_deposit=bool(payload.get("canDeposit", False)),
            can_withdraw=bool(payload.get("canWithdraw", False)),
            fee_tier=_as_int(payload.get("feeTier")),
            balances=balances,
            positions=positions,
        )

    def balances(self) -> list[FuturesBalance]:
        response = self._client.get("/fapi/v3/balance")
        rows = response.body if isinstance(response.body, list) else []
        return [_parse_balance(row) for row in rows if isinstance(row, dict)]

    def positions(self, symbol: str | None = None) -> list[FuturesPosition]:
        params: dict[str, Any] = {}
        if symbol:
            params["symbol"] = symbol.upper()
        response = self._client.get("/fapi/v3/positionRisk", params or None)
        rows = response.body if isinstance(response.body, list) else []
        return [_parse_position(row) for row in rows if isinstance(row, dict)]


def _parse_balance(entry: dict[str, Any]) -> FuturesBalance:
    return FuturesBalance(
        asset=str(entry.get("asset", "")),
        wallet_balance=_as_float(entry.get("walletBalance", entry.get("balance"))),
        available_balance=_as_float(entry.get("availableBalance")),
        cross_wallet_balance=_as_float(entry.get("crossWalletBalance")),
        cross_unrealized_pnl=_as_float(entry.get("crossUnPnl")),
        max_withdraw_amount=_as_float(entry.get("maxWithdrawAmount")),
        update_time=_as_int(entry.get("updateTime")),
    )


def _parse_position(entry: dict[str, Any]) -> FuturesPosition:
    margin_type = str(entry.get("marginType", "")).lower() or "cross"
    return FuturesPosition(
        symbol=str(entry.get("symbol", "")),
        position_side=str(entry.get("positionSide", "BOTH")),
        position_amount=_as_float(entry.get("positionAmt")),
        entry_price=_as_float(entry.get("entryPrice")),
        mark_price=_as_float(entry.get("markPrice")),
        unrealized_profit=_as_float(entry.get("unRealizedProfit", entry.get("unrealizedProfit"))),
        leverage=_as_int(entry.get("leverage")),
        liquidation_price=_as_float(entry.get("liquidationPrice")),
        margin_type=margin_type,
        isolated_wallet=_as_float(entry.get("isolatedWallet")),
        update_time=_as_int(entry.get("updateTime")),
    )
