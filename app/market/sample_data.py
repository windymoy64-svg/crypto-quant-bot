from __future__ import annotations

from app.core.models import Candle


def load_sample_candles(symbol: str) -> list[Candle]:
    prices = [
        100000, 100250, 100600, 100450, 100900, 101300, 101100, 101650,
        102000, 102400, 102250, 102850, 103300, 103800, 104100, 104650,
        104300, 104950, 105250, 105700, 106200, 106050, 106700, 107100,
        107650, 108000, 108450, 108250, 108900, 109400,
    ]
    candles: list[Candle] = []
    for index, close in enumerate(prices, start=1):
        open_price = prices[index - 2] if index > 1 else close - 150
        high = max(open_price, close) + 220
        low = min(open_price, close) - 260
        volume = 1000 + (index * 17) + (220 if index in {10, 18, 25, 29} else 0)
        candles.append(
            Candle(
                symbol=symbol,
                timestamp=f"2026-07-06T00:{index:02d}:00Z",
                open=float(open_price),
                high=float(high),
                low=float(low),
                close=float(close),
                volume=float(volume),
            )
        )
    return candles
