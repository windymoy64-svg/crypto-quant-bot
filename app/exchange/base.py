from __future__ import annotations

from abc import ABC, abstractmethod
from app.core.models import Candle


class ExchangeClient(ABC):
    @abstractmethod
    def fetch_candles(self, symbol: str, timeframe: str, limit: int) -> list[Candle]:
        raise NotImplementedError

    @abstractmethod
    def fetch_ticker(self, symbol: str) -> dict[str, float | str]:
        raise NotImplementedError
