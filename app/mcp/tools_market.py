"""Market data tools — thin wrap of MarketDataService (read-only).

Does not reimplement exchange clients. Scanner/regime/MTF stay internal.
"""

from __future__ import annotations

from typing import Any

from app.mcp.guards import err_payload, ok_payload, scrub_secrets

SUPPORTED_TIMEFRAMES: frozenset[str] = frozenset(
    {"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"}
)
SUPPORTED_EXCHANGES: frozenset[str] = frozenset({"binance", "bitunix", "okx"})
DEFAULT_EXCHANGE = "binance"
DEFAULT_TIMEFRAME = "1h"
DEFAULT_CANDLE_LIMIT = 100
MAX_CANDLE_LIMIT = 500
# force_refresh is capped: MCP operators may refresh, but default stays False
# so we do not stampede exchange APIs.


def _normalize_symbol(symbol: str) -> str:
    raw = str(symbol or "").strip().upper().replace("-", "/")
    if not raw:
        raise ValueError("symbol_required")
    if "/" not in raw and raw.endswith("USDT") and len(raw) > 4:
        # BTCUSDT -> BTC/USDT
        raw = f"{raw[:-4]}/{raw[-4:]}"
    return raw


def _normalize_timeframe(timeframe: str) -> str:
    tf = str(timeframe or DEFAULT_TIMEFRAME).strip().lower()
    if tf not in SUPPORTED_TIMEFRAMES:
        raise ValueError(
            f"unsupported_timeframe:{tf}; allowed={sorted(SUPPORTED_TIMEFRAMES)}"
        )
    return tf


def _normalize_exchange(exchange: str) -> str:
    ex = str(exchange or DEFAULT_EXCHANGE).strip().lower()
    if ex not in SUPPORTED_EXCHANGES:
        raise ValueError(
            f"unsupported_exchange:{ex}; allowed={sorted(SUPPORTED_EXCHANGES)}"
        )
    return ex


def _normalize_limit(limit: int) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError) as exc:
        raise ValueError("limit_must_be_int") from exc
    return max(1, min(value, MAX_CANDLE_LIMIT))


def _candle_to_dict(candle: object) -> dict[str, Any]:
    return {
        "symbol": getattr(candle, "symbol", None),
        "timestamp": getattr(candle, "timestamp", None),
        "open": float(getattr(candle, "open", 0.0) or 0.0),
        "high": float(getattr(candle, "high", 0.0) or 0.0),
        "low": float(getattr(candle, "low", 0.0) or 0.0),
        "close": float(getattr(candle, "close", 0.0) or 0.0),
        "volume": float(getattr(candle, "volume", 0.0) or 0.0),
    }


def get_candles(
    symbol: str,
    timeframe: str = DEFAULT_TIMEFRAME,
    limit: int = DEFAULT_CANDLE_LIMIT,
    exchange: str = DEFAULT_EXCHANGE,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Fetch OHLCV via existing MarketDataService (cache + exchange fallback)."""
    try:
        resolved_symbol = _normalize_symbol(symbol)
        resolved_tf = _normalize_timeframe(timeframe)
        resolved_limit = _normalize_limit(limit)
        resolved_exchange = _normalize_exchange(exchange)
        refresh = bool(force_refresh)

        from app.market.data_service import MarketDataService

        service = MarketDataService(
            exchange=resolved_exchange,
            fallback_to_sample_data=True,
        )
        result = service.fetch_ohlcv(
            symbol=resolved_symbol,
            timeframe=resolved_tf,
            limit=resolved_limit,
            force_refresh=refresh,
        )
        candles = [_candle_to_dict(c) for c in list(result.candles)]
        return ok_payload(
            {
                "available": True,
                "symbol": resolved_symbol,
                "timeframe": resolved_tf,
                "limit": resolved_limit,
                "exchange": resolved_exchange,
                "force_refresh": refresh,
                "source": result.source,
                "warning": result.warning,
                "count": len(candles),
                "candles": candles,
            }
        )
    except Exception as exc:  # noqa: BLE001
        return err_payload(exc, tool="get_candles")


def get_ticker(
    symbol: str,
    exchange: str = DEFAULT_EXCHANGE,
) -> dict[str, Any]:
    """Fetch ticker via existing MarketDataService."""
    try:
        resolved_symbol = _normalize_symbol(symbol)
        resolved_exchange = _normalize_exchange(exchange)

        from app.market.data_service import MarketDataService

        service = MarketDataService(
            exchange=resolved_exchange,
            fallback_to_sample_data=True,
        )
        ticker = service.fetch_ticker(resolved_symbol)
        cleaned = scrub_secrets(ticker) if isinstance(ticker, dict) else {"raw": ticker}
        if not isinstance(cleaned, dict):
            cleaned = {"raw": cleaned}
        return ok_payload(
            {
                "available": True,
                "symbol": resolved_symbol,
                "exchange": resolved_exchange,
                "ticker": cleaned,
            }
        )
    except Exception as exc:  # noqa: BLE001
        return err_payload(exc, tool="get_ticker")


def get_data_source(
    symbol: str,
    timeframe: str = DEFAULT_TIMEFRAME,
    limit: int = 5,
    exchange: str = DEFAULT_EXCHANGE,
) -> dict[str, Any]:
    """Return only source/warning metadata for a candle fetch (cheap debug)."""
    try:
        # Reuse get_candles with tiny limit; drop heavy candle list.
        full = get_candles(
            symbol=symbol,
            timeframe=timeframe,
            limit=limit,
            exchange=exchange,
            force_refresh=False,
        )
        if not full.get("ok"):
            return full
        return ok_payload(
            {
                "available": full.get("available", True),
                "symbol": full.get("symbol"),
                "timeframe": full.get("timeframe"),
                "exchange": full.get("exchange"),
                "source": full.get("source"),
                "warning": full.get("warning"),
                "count": full.get("count"),
            }
        )
    except Exception as exc:  # noqa: BLE001
        return err_payload(exc, tool="get_data_source")
