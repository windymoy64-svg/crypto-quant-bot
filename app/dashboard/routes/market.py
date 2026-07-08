from __future__ import annotations

from fastapi import APIRouter, Query

from app.dashboard.services import dashboard_service

router = APIRouter(prefix="/api", tags=["market"])


@router.get("/market")
def market() -> dict[str, object]:
    return dashboard_service.market()


@router.get("/klines")
def klines(
    symbol: str = Query(default="BTC/USDT", description="Trading pair, e.g. BTC/USDT"),
    timeframe: str = Query(default="1h", description="Candle interval, e.g. 1m, 5m, 1h, 1d"),
    limit: int = Query(default=200, ge=1, le=1000, description="Number of candles to return"),
    exchange: str = Query(default="binance", description="Exchange id used to source OHLCV data"),
) -> dict[str, object]:
    return dashboard_service.klines(
        symbol=symbol,
        timeframe=timeframe,
        limit=limit,
        exchange=exchange,
    )
