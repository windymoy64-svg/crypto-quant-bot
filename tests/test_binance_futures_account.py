from __future__ import annotations

from typing import Any

import pytest

from app.exchange.binance_futures.account import FuturesAccountReader
from app.exchange.binance_futures.client import FuturesHttpResponse


class _StubClient:
    """Minimal ``FuturesHttpClient`` replacement returning canned responses."""

    def __init__(self, responses: dict[str, Any]) -> None:
        self._responses = responses
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    def get(self, path, params=None, *, signed=True):  # noqa: ARG002
        self.calls.append((path, params))
        return FuturesHttpResponse(status_code=200, body=self._responses[path])

    def post(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("post should not be called in reader tests")

    def delete(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("delete should not be called in reader tests")


_ACCOUNT_BODY = {
    "totalWalletBalance": "1000.50",
    "totalUnrealizedProfit": "-15.20",
    "totalMarginBalance": "985.30",
    "availableBalance": "850.00",
    "maxWithdrawAmount": "820.00",
    "canTrade": True,
    "canDeposit": True,
    "canWithdraw": False,
    "feeTier": 2,
    "assets": [
        {
            "asset": "USDT",
            "walletBalance": "1000.50",
            "availableBalance": "850.00",
            "crossWalletBalance": "1000.50",
            "crossUnPnl": "-15.20",
            "maxWithdrawAmount": "820.00",
            "updateTime": 1234567890,
        }
    ],
    "positions": [
        {
            "symbol": "BTCUSDT",
            "positionSide": "BOTH",
            "positionAmt": "0.005",
            "entryPrice": "60000",
            "markPrice": "61200",
            "unRealizedProfit": "6.0",
            "leverage": "10",
            "liquidationPrice": "55000",
            "marginType": "ISOLATED",
            "isolatedWallet": "30.0",
            "updateTime": 1234567891,
        }
    ],
}

_BALANCE_BODY = [
    {
        "asset": "BUSD",
        "balance": "500.0",
        "availableBalance": "500.0",
        "crossWalletBalance": "500.0",
        "crossUnPnl": "0",
        "maxWithdrawAmount": "500.0",
        "updateTime": 999,
    }
]

_POSITION_RISK_BODY = [
    {
        "symbol": "ETHUSDT",
        "positionSide": "LONG",
        "positionAmt": "0.5",
        "entryPrice": "3000",
        "markPrice": "3100",
        "unRealizedProfit": "50",
        "leverage": "5",
        "liquidationPrice": "2500",
        "marginType": "cross",
        "isolatedWallet": "0",
        "updateTime": 12345,
    }
]


def _reader(responses: dict[str, Any]) -> tuple[FuturesAccountReader, _StubClient]:
    stub = _StubClient(responses)
    return FuturesAccountReader(stub), stub


def test_snapshot_parses_account_payload() -> None:
    reader, stub = _reader({"/fapi/v3/account": _ACCOUNT_BODY})

    snapshot = reader.snapshot()

    assert stub.calls == [("/fapi/v3/account", None)]
    assert snapshot.total_wallet_balance == pytest.approx(1000.50)
    assert snapshot.can_trade is True
    assert snapshot.can_withdraw is False
    assert snapshot.fee_tier == 2

    assert len(snapshot.balances) == 1
    balance = snapshot.balances[0]
    assert balance.asset == "USDT"
    assert balance.available_balance == pytest.approx(850.00)

    assert len(snapshot.positions) == 1
    position = snapshot.positions[0]
    assert position.symbol == "BTCUSDT"
    assert position.position_amount == pytest.approx(0.005)
    assert position.leverage == 10
    assert position.margin_type == "isolated"
    assert position.liquidation_price == pytest.approx(55000.0)


def test_balances_endpoint_returns_list() -> None:
    reader, stub = _reader({"/fapi/v3/balance": _BALANCE_BODY})

    balances = reader.balances()

    assert stub.calls == [("/fapi/v3/balance", None)]
    assert [b.asset for b in balances] == ["BUSD"]
    assert balances[0].wallet_balance == pytest.approx(500.0)


def test_positions_forwards_symbol_uppercased() -> None:
    reader, stub = _reader({"/fapi/v3/positionRisk": _POSITION_RISK_BODY})

    positions = reader.positions(symbol="ethusdt")

    assert stub.calls == [("/fapi/v3/positionRisk", {"symbol": "ETHUSDT"})]
    assert positions[0].symbol == "ETHUSDT"
    assert positions[0].position_side == "LONG"
    assert positions[0].margin_type == "cross"


def test_snapshot_handles_missing_fields_gracefully() -> None:
    reader, _ = _reader({"/fapi/v3/account": {}})

    snapshot = reader.snapshot()

    assert snapshot.total_wallet_balance == 0.0
    assert snapshot.balances == []
    assert snapshot.positions == []
    assert snapshot.can_trade is False
