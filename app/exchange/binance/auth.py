from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from app.exchange.binance.exceptions import BinanceConfigurationError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BinanceCredentials:
    api_key: str
    api_secret: str

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_secret)


class BinanceAuth:
    def __init__(self, env_path: str | Path = ".env") -> None:
        self.env_path = Path(env_path)

    def credentials(self, *, required: bool = False) -> BinanceCredentials:
        env = self._read_env_file()
        api_key = (
            os.getenv("BINANCE_API_KEY")
            or env.get("BINANCE_API_KEY")
            or os.getenv("EXCHANGE_API_KEY")
            or env.get("EXCHANGE_API_KEY")
            or ""
        )
        api_secret = (
            os.getenv("BINANCE_API_SECRET")
            or env.get("BINANCE_API_SECRET")
            or os.getenv("EXCHANGE_SECRET")
            or env.get("EXCHANGE_SECRET")
            or ""
        )

        # Fallback to the encrypted secrets store populated via the dashboard
        # Settings panel. Env vars still win to preserve deployment overrides.
        if not (api_key and api_secret):
            stored = self._load_from_secrets_store()
            if stored is not None:
                api_key = api_key or stored.api_key
                api_secret = api_secret or stored.api_secret

        credentials = BinanceCredentials(
            api_key=api_key.strip(), api_secret=api_secret.strip()
        )
        if required and not credentials.is_configured:
            raise BinanceConfigurationError(
                "Binance API credentials are required for private read-only endpoints"
            )
        return credentials

    def _read_env_file(self) -> dict[str, str]:
        if not self.env_path.exists():
            return {}
        result: dict[str, str] = {}
        for raw_line in self.env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            result[key.strip()] = value.strip().strip('"').strip("'")
        return result

    @staticmethod
    def _load_from_secrets_store() -> "BinanceCredentials | None":
        try:
            from app.settings.exchange_credentials import load_exchange_credentials
        except Exception:  # pragma: no cover - defensive: cryptography missing
            logger.debug(
                "Secrets store unavailable; skipping stored credentials lookup",
                exc_info=True,
            )
            return None
        try:
            record = load_exchange_credentials()
        except Exception:  # pragma: no cover - defensive: DB / key errors
            logger.warning(
                "Failed to load Binance credentials from secrets store",
                exc_info=True,
            )
            return None
        if record is None or not record.is_configured:
            return None
        return BinanceCredentials(
            api_key=record.api_key,
            api_secret=record.api_secret,
        )
