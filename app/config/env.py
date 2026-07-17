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
    api_key = os.getenv("EXCHANGE_API_KEY", "") or os.getenv("BINANCE_API_KEY", "")
    secret = os.getenv("EXCHANGE_SECRET", "") or os.getenv("BINANCE_API_SECRET", "")

    # Fall back to the encrypted secrets store (populated from the dashboard
    # Settings panel) so operators can rotate credentials without editing .env.
    # Env variables retain precedence to keep deployment overrides possible.
    if not (api_key and secret):
        stored = _load_stored_binance_credentials()
        if stored is not None:
            api_key = api_key or stored[0]
            secret = secret or stored[1]

    return ExchangeCredentials(
        exchange_id=os.getenv("EXCHANGE_ID", "binance"),
        api_key=api_key,
        secret=secret,
        password=password,
    )


def _load_stored_binance_credentials() -> tuple[str, str] | None:
    try:
        from app.settings.exchange_credentials import load_exchange_credentials
    except Exception:
        return None
    try:
        record = load_exchange_credentials()
    except Exception:
        return None
    if record is None or not record.is_configured:
        return None
    return record.api_key, record.api_secret


def get_bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}