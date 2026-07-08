from __future__ import annotations

from app.live import AccountPreflightEngine, AccountPreflightValidator, AccountSnapshot, LiveConfig, LiveOrder, OpenOrderSummary


def _account(can_trade: bool = True, permissions: list[str] | None = None, usdt: float = 500.0) -> AccountSnapshot:
    return AccountSnapshot(
        account_type="SPOT",
        can_trade=can_trade,
        can_withdraw=True,
        can_deposit=True,
        maker_commission=10,
        taker_commission=10,
        buyer_commission=0,
        seller_commission=0,
        balances={"USDT": {"free": usdt, "locked": 0.0}},
        permissions=permissions if permissions is not None else ["SPOT"],
        update_time=123456789,
    )


def _order() -> LiveOrder:
    return LiveOrder(
        symbol="BTC/USDT",
        side="BUY",
        order_type="MARKET",
        quantity=0.001,
        quote_amount=100.0,
        price=100000.0,
        stop_loss=99000.0,
        take_profit=101500.0,
        timestamp="2026-07-07T00:00:00+00:00",
    )


def _open_order(symbol: str = "BTCUSDT", side: str = "BUY") -> OpenOrderSummary:
    return OpenOrderSummary(
        symbol=symbol,
        side=side,
        type="MARKET",
        status="NEW",
        orig_qty=0.001,
        executed_qty=0.0,
        price=100000.0,
    )


class Reader:
    def __init__(self, account: AccountSnapshot, open_orders: list[OpenOrderSummary] | None = None) -> None:
        self.account = account
        self.orders = open_orders or []

    def account_snapshot(self) -> AccountSnapshot:
        return self.account

    def open_orders(self, symbol: str | None = None) -> list[OpenOrderSummary]:
        return self.orders


def test_account_preflight_accepts_valid_account() -> None:
    result = AccountPreflightEngine(Reader(_account()), LiveConfig()).validate(_order(), exchange_validated=True)

    assert result.approved is True
    assert result.reason == "account_preflight_approved"


def test_account_preflight_rejects_account_cannot_trade() -> None:
    result = AccountPreflightEngine(Reader(_account(can_trade=False)), LiveConfig()).validate(_order(), exchange_validated=True)

    assert result.approved is False
    assert result.reason == "account_cannot_trade"


def test_account_preflight_rejects_insufficient_balance() -> None:
    result = AccountPreflightEngine(Reader(_account(usdt=50.0)), LiveConfig()).validate(_order(), exchange_validated=True)

    assert result.approved is False
    assert result.reason == "account_quote_balance_below_minimum"


def test_account_preflight_rejects_duplicate_order() -> None:
    result = AccountPreflightEngine(Reader(_account(), [_open_order()]), LiveConfig()).validate(_order(), exchange_validated=True)

    assert result.approved is False
    assert result.reason == "account_duplicate_order_for_symbol"


def test_account_preflight_rejects_open_order_limit() -> None:
    config = LiveConfig(max_open_orders=2)
    result = AccountPreflightEngine(
        Reader(_account(), [_open_order("ETHUSDT"), _open_order("BNBUSDT")]),
        config,
    ).validate(_order(), exchange_validated=True)

    assert result.approved is False
    assert result.reason == "account_open_order_limit_reached"


def test_account_preflight_rejects_daily_order_limit() -> None:
    config = LiveConfig(max_daily_orders=1)
    result = AccountPreflightEngine(Reader(_account()), config).validate(_order(), daily_orders=1, exchange_validated=True)

    assert result.approved is False
    assert result.reason == "account_daily_order_limit_reached"


def test_account_preflight_rejects_no_spot_permission() -> None:
    result = AccountPreflightEngine(Reader(_account(permissions=["MARGIN"])), LiveConfig()).validate(_order(), exchange_validated=True)

    assert result.approved is False
    assert result.reason == "account_spot_permission_required"


def test_account_validator_returns_approved() -> None:
    result = AccountPreflightValidator(LiveConfig()).validate(
        order=_order(),
        account_snapshot=_account(),
        open_orders=[],
        daily_orders=0,
        exchange_validated=True,
    )

    assert result.approved is True
    assert result.reason == "account_preflight_approved"