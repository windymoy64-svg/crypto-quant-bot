from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

from app.live.exchange_rules import BinanceExchangeInfoLoader, ExchangeInfo


class ExchangeInfoCache:
    def __init__(
        self,
        loader: BinanceExchangeInfoLoader | None = None,
        *,
        cache_path: str | Path = "logs/exchange_info_cache.json",
        ttl_seconds: int = 3600,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.loader = loader or BinanceExchangeInfoLoader()
        self.cache_path = Path(cache_path)
        self.ttl_seconds = ttl_seconds
        self.clock = clock or time.time
        self._memory: tuple[float, ExchangeInfo] | None = None

    def get(self, *, force_refresh: bool = False) -> ExchangeInfo:
        if not force_refresh:
            cached = self._get_memory_cache() or self._get_file_cache()
            if cached is not None:
                return cached

        fresh = self.loader.fetch()
        self._memory = (self.clock(), fresh)
        self._write_file_cache(fresh)
        return fresh

    def _get_memory_cache(self) -> ExchangeInfo | None:
        if self._memory is None:
            return None
        fetched_at, info = self._memory
        return info if self._is_valid(fetched_at) else None

    def _get_file_cache(self) -> ExchangeInfo | None:
        if not self.cache_path.exists():
            return None
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError:
            return None
        fetched_at = float(payload.get("fetched_at", 0.0))
        if not self._is_valid(fetched_at):
            return None
        info = ExchangeInfo.from_dict(payload.get("data", {}))
        self._memory = (fetched_at, info)
        return info

    def _write_file_cache(self, info: ExchangeInfo) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"fetched_at": self.clock(), "data": info.to_dict()}
        self.cache_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    def _is_valid(self, fetched_at: float) -> bool:
        return (self.clock() - fetched_at) < self.ttl_seconds