from __future__ import annotations

from dataclasses import dataclass

from app.core.models import Candle
from app.exchange.base import ExchangeClient
from app.exchange.ccxt_client import CcxtExchangeClient
from app.exchange.public_http_client import PublicHttpExchangeClient
from app.market.sample_data import load_sample_candles


@dataclass(frozen=True)
class CandleLoadResult:
    symbol: str
    exchange: str
    timeframe: str
    candles: list[Candle]
    source: str
    warning: str | None = None


def load_market_candles(
    symbol: str,
    exchange: str,
    timeframe: str,
    limit: int,
    *,
    fallback_to_sample_data: bool = True,
    client: ExchangeClient | None = None,
) -> CandleLoadResult:
    errors: list[str] = []
    try:
        exchange_client = client or CcxtExchangeClient(exchange)
        candles = exchange_client.fetch_candles(symbol=symbol, timeframe=timeframe, limit=limit)
        if not candles:
            raise RuntimeError("exchange returned no candles")
        return CandleLoadResult(
            symbol=symbol,
            exchange=exchange,
            timeframe=timeframe,
            candles=candles,
            source="live",
        )
    except Exception as exc:
        errors.append(f"ccxt: {exc}")

    if client is None:
        try:
            public_client = PublicHttpExchangeClient(exchange)
            candles = public_client.fetch_candles(symbol=symbol, timeframe=timeframe, limit=limit)
            if not candles:
                raise RuntimeError("exchange returned no candles")
            return CandleLoadResult(
                symbol=symbol,
                exchange=exchange,
                timeframe=timeframe,
                candles=candles,
                source="public_http",
                warning="; ".join(errors) if errors else None,
            )
        except Exception as exc:
            errors.append(f"public_http: {exc}")

    if not fallback_to_sample_data:
        raise RuntimeError("; ".join(errors))

    return CandleLoadResult(
        symbol=symbol,
        exchange=exchange,
        timeframe=timeframe,
        candles=load_sample_candles(symbol),
        source="sample",
        warning=f"live data unavailable: {'; '.join(errors)}",
    )
