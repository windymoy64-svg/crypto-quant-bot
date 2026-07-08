from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from app.exchange.binance.exceptions import BinanceConfigurationError


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
        api_key = os.getenv("BINANCE_API_KEY") or env.get("BINANCE_API_KEY") or os.getenv("EXCHANGE_API_KEY") or env.get("EXCHANGE_API_KEY") or ""
        api_secret = os.getenv("BINANCE_API_SECRET") or env.get("BINANCE_API_SECRET") or os.getenv("EXCHANGE_SECRET") or env.get("EXCHANGE_SECRET") or ""
        credentials = BinanceCredentials(api_key=api_key.strip(), api_secret=api_secret.strip())
        if required and not credentials.is_configured:
            raise BinanceConfigurationError("Binance API credentials are required for private read-only endpoints")
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