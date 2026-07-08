from __future__ import annotations

from app.live import ExchangeInfo, ExchangeInfoCache, ExchangeSymbolRules, ExchangeValidator, LiveOrder


def _rules(status: str = "TRADING") -> ExchangeInfo:
    return ExchangeInfo(
        symbols={
            "BTCUSDT": ExchangeSymbolRules(
                symbol="BTCUSDT",
                status=status,
                baseAsset="BTC",
                quoteAsset="USDT",
                basePrecision=8,
                quotePrecision=8,
                orderTypes=["LIMIT", "MARKET"],
                permissions=["SPOT"],
                filters={
                    "PRICE_FILTER": {"minPrice": "0.01", "maxPrice": "1000000", "tickSize": "0.01"},
                    "LOT_SIZE": {"minQty": "0.001", "maxQty": "100", "stepSize": "0.001"},
                    "MARKET_LOT_SIZE": {"minQty": "0.001", "maxQty": "100", "stepSize": "0.001"},
                    "MIN_NOTIONAL": {"minNotional": "10"},
                    "NOTIONAL": {"minNotional": "10", "maxNotional": "1000000"},
                    "MAX_NUM_ORDERS": {"maxNumOrders": 200},
                },
            )
        }
    )


def _order(**overrides: object) -> LiveOrder:
    values = {
        "symbol": "BTC/USDT",
        "side": "BUY",
        "order_type": "MARKET",
        "quantity": 0.01,
        "quote_amount": 100.0,
        "price": 100000.0,
        "stop_loss": 99000.0,
        "take_profit": 101500.0,
        "timestamp": "2026-07-07T00:00:00+00:00",
    }
    values.update(overrides)
    return LiveOrder(**values)


class CountingLoader:
    def __init__(self, info: ExchangeInfo) -> None:
        self.info = info
        self.calls = 0

    def fetch(self) -> ExchangeInfo:
        self.calls += 1
        return self.info


def test_exchange_validator_accepts_valid_symbol() -> None:
    result = ExchangeValidator(_rules()).validate(_order())

    assert result.valid is True
    assert result.reason == "exchange_rules_approved"


def test_exchange_validator_rejects_invalid_symbol() -> None:
    result = ExchangeValidator(_rules()).validate(_order(symbol="ETH/USDT"))

    assert result.valid is False
    assert result.reason == "exchange_symbol_not_found:ETHUSDT"


def test_exchange_validator_rejects_min_notional() -> None:
    result = ExchangeValidator(_rules()).validate(_order(quote_amount=5.0))

    assert result.valid is False
    assert result.reason.startswith("exchange_min_notional")


def test_exchange_validator_rejects_lot_size_min_quantity() -> None:
    result = ExchangeValidator(_rules()).validate(_order(quantity=0.0005))

    assert result.valid is False
    assert result.reason.startswith("exchange_lot_size_min_qty")


def test_exchange_validator_rejects_step_size() -> None:
    result = ExchangeValidator(_rules()).validate(_order(quantity=0.0105))

    assert result.valid is False
    assert result.reason.startswith("exchange_lot_size_step_size")


def test_exchange_validator_rejects_tick_size() -> None:
    result = ExchangeValidator(_rules()).validate(_order(price=100000.005))

    assert result.valid is False
    assert result.reason.startswith("exchange_price_tick_size")


def test_exchange_validator_rejects_non_trading_status() -> None:
    result = ExchangeValidator(_rules(status="BREAK")).validate(_order())

    assert result.valid is False
    assert result.reason == "exchange_symbol_not_trading:BTCUSDT:BREAK"


def test_exchange_info_cache_hit_does_not_refetch(tmp_path) -> None:
    loader = CountingLoader(_rules())
    now = [1000.0]
    cache = ExchangeInfoCache(loader, cache_path=tmp_path / "exchange.json", ttl_seconds=3600, clock=lambda: now[0])

    cache.get()
    cache.get()

    assert loader.calls == 1


def test_exchange_info_cache_miss_refetches_after_ttl(tmp_path) -> None:
    loader = CountingLoader(_rules())
    now = [1000.0]
    cache = ExchangeInfoCache(loader, cache_path=tmp_path / "exchange.json", ttl_seconds=10, clock=lambda: now[0])

    cache.get()
    now[0] = 1011.0
    cache.get()

    assert loader.calls == 2