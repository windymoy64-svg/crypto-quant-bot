"""Per-exchange trading defaults configured from the dashboard.

All values are optional. Missing values deliberately preserve the existing
signal, ATR, and exchange defaults used by the runtime.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.settings.exchange_credentials import DEFAULT_EXCHANGE, SUPPORTED_EXCHANGES
from app.settings.store import SecretsStore, get_secrets_store


LEVERAGE_LIMITS: dict[str, tuple[int, int]] = {
    "binance": (1, 125),
    "bitunix": (1, 125),
}


@dataclass(frozen=True)
class TradingPreferences:
    exchange: str
    take_profit_percent: float | None = None
    stop_loss_percent: float | None = None
    trailing_stop_percent: float | None = None
    leverage: int | None = None
    updated_at: str | None = None


def leverage_options(exchange: str) -> list[int]:
    minimum, maximum = LEVERAGE_LIMITS[_normalize_exchange(exchange)]
    return list(range(minimum, maximum + 1))


def load_trading_preferences(
    store: SecretsStore | None = None,
    *,
    exchange: str = DEFAULT_EXCHANGE,
) -> TradingPreferences:
    store = store or get_secrets_store()
    exchange = _normalize_exchange(exchange)
    values = {
        "take_profit_percent": _optional_float(
            store.get(_key(exchange, "take_profit_percent"))
        ),
        "stop_loss_percent": _optional_float(
            store.get(_key(exchange, "stop_loss_percent"))
        ),
        "trailing_stop_percent": _optional_float(
            store.get(_key(exchange, "trailing_stop_percent"))
        ),
        "leverage": _optional_int(store.get(_key(exchange, "leverage"))),
    }
    timestamps = [
        store.updated_at(_key(exchange, field))
        for field in values
        if values[field] is not None
    ]
    return TradingPreferences(
        exchange=exchange,
        updated_at=max((value for value in timestamps if value), default=None),
        **values,
    )


def save_trading_preferences(
    *,
    exchange: str = DEFAULT_EXCHANGE,
    take_profit_percent: float | None = None,
    stop_loss_percent: float | None = None,
    trailing_stop_percent: float | None = None,
    leverage: int | None = None,
    store: SecretsStore | None = None,
) -> TradingPreferences:
    store = store or get_secrets_store()
    exchange = _normalize_exchange(exchange)
    values: dict[str, float | int | None] = {
        "take_profit_percent": _validate_percent(
            "take_profit_percent", take_profit_percent
        ),
        "stop_loss_percent": _validate_percent("stop_loss_percent", stop_loss_percent),
        "trailing_stop_percent": _validate_percent(
            "trailing_stop_percent", trailing_stop_percent
        ),
        "leverage": _validate_leverage(exchange, leverage),
    }
    for field, value in values.items():
        key = _key(exchange, field)
        if value is None:
            store.delete(key)
        else:
            store.set(key, str(value))
    return load_trading_preferences(store=store, exchange=exchange)


def _normalize_exchange(exchange: str | None) -> str:
    value = (exchange or DEFAULT_EXCHANGE).strip().lower()
    if value not in SUPPORTED_EXCHANGES:
        raise ValueError(
            f"Unsupported exchange {value!r}; expected one of {SUPPORTED_EXCHANGES}"
        )
    return value


def _key(exchange: str, field: str) -> str:
    return f"{exchange}.trading.{field}"


def _optional_float(value: str | None) -> float | None:
    return None if value is None or not value.strip() else float(value)


def _optional_int(value: str | None) -> int | None:
    return None if value is None or not value.strip() else int(value)


def _validate_percent(name: str, value: float | None) -> float | None:
    if value is None:
        return None
    parsed = float(value)
    if not 0 < parsed <= 100:
        raise ValueError(f"{name} must be within (0, 100]")
    return parsed


def _validate_leverage(exchange: str, value: int | None) -> int | None:
    if value is None:
        return None
    parsed = int(value)
    minimum, maximum = LEVERAGE_LIMITS[exchange]
    if not minimum <= parsed <= maximum:
        raise ValueError(
            f"leverage for {exchange} must be within [{minimum}, {maximum}]"
        )
    return parsed