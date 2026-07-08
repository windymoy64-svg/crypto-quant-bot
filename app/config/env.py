from __future__ import annotations

import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dotenv is optional at runtime
    load_dotenv = None

# Load .env dari root project bila python-dotenv tersedia.
# app.config.production.load_dotenv_file() menjadi fallback saat paket ini tidak
# terpasang, jadi kegagalan import tidak boleh menghentikan startup.
if load_dotenv is not None:
    load_dotenv()



@dataclass(frozen=True)
class ExchangeCredentials:
    exchange_id: str
    api_key: str
    secret: str
    password: str | None

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.secret)


def get_exchange_credentials() -> ExchangeCredentials:
    password = os.getenv("EXCHANGE_PASSWORD") or None

    return ExchangeCredentials(
        exchange_id=os.getenv("EXCHANGE_ID", "binance"),
        api_key=os.getenv("EXCHANGE_API_KEY", ""),
        secret=os.getenv("EXCHANGE_SECRET", ""),
        password=password,
    )


def get_bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}