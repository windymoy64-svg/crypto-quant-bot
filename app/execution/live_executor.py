from __future__ import annotations

from dataclasses import dataclass

from app.config.env import get_bool_env, get_exchange_credentials
from app.exchange.ccxt_client import CcxtExchangeClient


@dataclass(frozen=True)
class LiveTradingSettings:
    enabled: bool
    dry_run: bool
    exchange: str
    quote_asset: str
    max_order_notional: float
    allowed_symbols: list[str]
    min_confidence: float
    allow_market_orders: bool

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "LiveTradingSettings":
        env_enabled = get_bool_env("LIVE_TRADING_ENABLED", bool(data.get("enabled", False)))
        env_dry_run = get_bool_env("LIVE_TRADING_DRY_RUN", bool(data.get("dry_run", True)))
        return cls(
            enabled=env_enabled,
            dry_run=env_dry_run,
            exchange=str(data.get("exchange", "binance")),
            quote_asset=str(data.get("quote_asset", "USDT")),
            max_order_notional=float(data.get("max_order_notional", 25)),
            allowed_symbols=[str(symbol) for symbol in data.get("allowed_symbols", [])],
            min_confidence=float(data.get("min_confidence", 95)),
            allow_market_orders=bool(data.get("allow_market_orders", True)),
        )


class LiveExecutor:
    def __init__(self, settings: LiveTradingSettings) -> None:
        self.settings = settings

    def evaluate_signal(self, signal: dict[str, object]) -> dict[str, object]:
        symbol = str(signal.get("symbol", ""))
        action = str(signal.get("action", ""))
        confidence = float(signal.get("confidence", 0))

        if not self.settings.enabled:
            return self._decision("blocked", symbol, "live_trading_disabled", signal)
        if self.settings.dry_run:
            return self._decision("dry_run", symbol, "dry_run_enabled", signal)
        if not self.settings.allow_market_orders:
            return self._decision("blocked", symbol, "market_orders_disabled", signal)
        if symbol not in self.settings.allowed_symbols:
            return self._decision("blocked", symbol, "symbol_not_allowed", signal)
        if action != "BUY":
            return self._decision("ignored", symbol, f"action={action}", signal)
        if confidence < self.settings.min_confidence:
            return self._decision("blocked", symbol, "confidence_too_low", signal)

        credentials = get_exchange_credentials()
        if not credentials.configured:
            return self._decision("blocked", symbol, "exchange_credentials_missing", signal)

        amount = self._calculate_base_amount(signal)
        client = CcxtExchangeClient(
            credentials.exchange_id,
            api_key=credentials.api_key,
            secret=credentials.secret,
            password=credentials.password,
        )
        order = client.create_market_order(symbol=symbol, side="buy", amount=amount)
        return {
            "status": "submitted",
            "symbol": symbol,
            "reason": "market_buy_order_submitted",
            "amount": amount,
            "order": order,
        }

    def _calculate_base_amount(self, signal: dict[str, object]) -> float:
        entry = float(signal["entry"])
        if entry <= 0:
            raise ValueError("entry must be positive")
        return round(self.settings.max_order_notional / entry, 8)

    def _decision(
        self,
        status: str,
        symbol: str,
        reason: str,
        signal: dict[str, object],
    ) -> dict[str, object]:
        return {
            "status": status,
            "symbol": symbol,
            "reason": reason,
            "action": signal.get("action"),
            "confidence": signal.get("confidence"),
            "dry_run": self.settings.dry_run,
            "enabled": self.settings.enabled,
        }
