"""Reject unsafe OHLCV input before it reaches trading logic."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class DataIntegrityResult:
    is_valid: bool
    is_synthetic: bool = False
    data_source: str | None = None
    errors: list[str] = field(default_factory=list)


class DataIntegrityGate:
    def __init__(self, max_freshness_seconds: int = 300) -> None:
        self.max_freshness_seconds = max(1, int(max_freshness_seconds))

    def validate_ohlcv(
        self, candles: list[dict[str, Any]], symbol: str, timeframe: str
    ) -> DataIntegrityResult:
        errors: list[str] = []
        if not candles:
            return DataIntegrityResult(False, errors=["No data provided"])

        timestamps = [item.get("timestamp") for item in candles]
        if len(set(timestamps)) != len(timestamps):
            errors.append("Duplicate candles detected")

        synthetic = any(bool(item.get("is_synthetic")) for item in candles)
        if synthetic:
            errors.append("Synthetic data detected - reject")

        for item in candles:
            try:
                open_price = float(item["open"])
                high = float(item["high"])
                low = float(item["low"])
                close = float(item["close"])
                volume = float(item["volume"])
            except (KeyError, TypeError, ValueError):
                errors.append("Invalid OHLCV values")
                continue
            if not (low <= open_price <= high and low <= close <= high):
                errors.append("Invalid OHLC values")
            if volume < 0:
                errors.append("Negative volume")

        latest = timestamps[-1]
        try:
            age = datetime.now(timezone.utc).timestamp() - float(latest) / 1000
            interval_seconds = _timeframe_seconds(timeframe)
            if age > max(self.max_freshness_seconds, interval_seconds) + 5:
                errors.append("Data is stale")
        except (TypeError, ValueError):
            errors.append("Invalid timestamp")

        return DataIntegrityResult(
            is_valid=not errors,
            is_synthetic=synthetic,
            data_source=str(candles[0].get("exchange") or "unknown"),
            errors=list(dict.fromkeys(errors)),
        )


def _timeframe_seconds(timeframe: str) -> int:
    value = str(timeframe or "").strip().lower()
    if value.endswith("m"):
        return int(value[:-1] or 0) * 60
    if value.endswith("h"):
        return int(value[:-1] or 0) * 3600
    if value.endswith("d"):
        return int(value[:-1] or 0) * 86400
    return 0
