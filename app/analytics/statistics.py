from __future__ import annotations

from datetime import datetime
from math import sqrt
from statistics import mean as statistics_mean
from typing import Iterable


def safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def mean(values: Iterable[float]) -> float:
    values_list = list(values)
    return statistics_mean(values_list) if values_list else 0.0


def sample_stddev(values: Iterable[float]) -> float:
    values_list = list(values)
    if len(values_list) < 2:
        return 0.0
    average = mean(values_list)
    variance = sum((value - average) ** 2 for value in values_list) / (len(values_list) - 1)
    return sqrt(variance)


def downside_stddev(values: Iterable[float], target_return: float = 0.0) -> float:
    downside = [min(value - target_return, 0.0) for value in values]
    if len(downside) < 2:
        return 0.0
    return sqrt(sum(value**2 for value in downside) / (len(downside) - 1))


def parse_timestamp(value: object) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def period_key(timestamp: object, period: str) -> str:
    parsed = parse_timestamp(timestamp)
    if parsed is None:
        return "unknown"
    normalized = period.lower()
    if normalized == "daily":
        return parsed.strftime("%Y-%m-%d")
    if normalized == "weekly":
        year, week, _ = parsed.isocalendar()
        return f"{year}-W{week:02d}"
    if normalized == "monthly":
        return parsed.strftime("%Y-%m")
    return "unknown"


def round_float(value: float, digits: int = 4) -> float:
    return round(value, digits)