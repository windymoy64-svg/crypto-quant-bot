"""Structure reader — BOS, CHoCH, Order Blocks, Breaker Blocks.

Extends the existing liquidity_structure module with additional smart money
concepts. All functions are pure and deterministic.
"""

from __future__ import annotations

from app.core.models import Candle
from app.chart_agent.models import OrderBlock, BreakerBlock, StructureBreak


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_bullish(c: Candle) -> bool:
    return c.close > c.open


def _is_bearish(c: Candle) -> bool:
    return c.close < c.open


def _body_top(c: Candle) -> float:
    return max(c.open, c.close)


def _body_bottom(c: Candle) -> float:
    return min(c.open, c.close)


# ---------------------------------------------------------------------------
# BOS & CHoCH detection
# ---------------------------------------------------------------------------


def detect_structure_breaks(
    candles: list[Candle],
    swing_lookback: int = 5,
) -> list[StructureBreak]:
    """Detect BOS and CHoCH from swing structure.

    BOS (Break of Structure): price breaks a swing point in the direction
    of the current trend (continuation).
    CHoCH (Change of Character): price breaks a swing point against the
    current trend (potential reversal).

    Uses a simple fractal swing detection (3-candle) and tracks the
    current trend state to classify each break.
    """
    if len(candles) < 5:
        return []

    # Find swing highs and lows (3-candle fractal)
    swing_highs: list[tuple[int, float]] = []
    swing_lows: list[tuple[int, float]] = []

    for i in range(1, len(candles) - 1):
        left, mid, right = candles[i - 1], candles[i], candles[i + 1]
        if mid.high > left.high and mid.high > right.high:
            swing_highs.append((i, mid.high))
        if mid.low < left.low and mid.low < right.low:
            swing_lows.append((i, mid.low))

    if not swing_highs or not swing_lows:
        return []

    # Track trend and detect breaks
    breaks: list[StructureBreak] = []
    current_trend = "NEUTRAL"  # UP, DOWN, NEUTRAL

    # Determine initial trend from first swings
    if len(swing_highs) >= 2 and len(swing_lows) >= 2:
        if swing_highs[-1][1] > swing_highs[-2][1] and swing_lows[-1][1] > swing_lows[-2][1]:
            current_trend = "UP"
        elif swing_highs[-1][1] < swing_highs[-2][1] and swing_lows[-1][1] < swing_lows[-2][1]:
            current_trend = "DOWN"

    # Check recent candles for breaking swing levels
    for i in range(max(3, len(candles) - swing_lookback), len(candles)):
        c = candles[i]

        # Check if current candle breaks any swing high
        for sh_idx, sh_price in reversed(swing_highs):
            if sh_idx >= i:
                continue
            if c.close > sh_price:
                if current_trend == "UP" or current_trend == "NEUTRAL":
                    btype = "BOS"
                else:
                    btype = "CHoCH"
                breaks.append(StructureBreak(
                    break_type=btype,
                    direction="BULLISH",
                    price=sh_price,
                    index=i,
                    timestamp=c.timestamp,
                    swing_origin_index=sh_idx,
                ))
                break

        # Check if current candle breaks any swing low
        for sl_idx, sl_price in reversed(swing_lows):
            if sl_idx >= i:
                continue
            if c.close < sl_price:
                if current_trend == "DOWN" or current_trend == "NEUTRAL":
                    btype = "BOS"
                else:
                    btype = "CHoCH"
                breaks.append(StructureBreak(
                    break_type=btype,
                    direction="BEARISH",
                    price=sl_price,
                    index=i,
                    timestamp=c.timestamp,
                    swing_origin_index=sl_idx,
                ))
                break

    return breaks


# ---------------------------------------------------------------------------
# Order Block detection
# ---------------------------------------------------------------------------


def detect_order_blocks(
    candles: list[Candle],
    min_displacement_ratio: float = 1.5,
) -> list[OrderBlock]:
    """Detect order blocks (last opposing candle before strong displacement).

    Bullish OB: last bearish candle before a strong bullish move (displacement).
    Bearish OB: last bullish candle before a strong bearish move (displacement).

    Displacement is defined as a candle with body >= min_displacement_ratio * ATR.
    """
    if len(candles) < 5:
        return []

    # Calculate simple ATR for displacement threshold
    atr_sum = 0.0
    for c in candles[-20:]:
        atr_sum += c.high - c.low
    atr = atr_sum / min(20, len(candles))

    obs: list[OrderBlock] = []
    current_price = candles[-1].close

    for i in range(2, len(candles)):
        c = candles[i]
        body = abs(c.close - c.open)

        # Strong bullish displacement
        if _is_bullish(c) and body >= atr * min_displacement_ratio:
            # Look for last bearish candle before this
            for j in range(i - 1, max(i - 4, -1), -1):
                if _is_bearish(candles[j]):
                    ob_top = candles[j].open  # body top of bearish = open
                    ob_bottom = candles[j].close  # body bottom = close
                    # Check if mitigated (price came back into OB)
                    mitigated = any(
                        candles[k].low <= ob_top
                        for k in range(i + 1, len(candles))
                    )
                    tested = current_price <= ob_top and current_price >= ob_bottom
                    obs.append(OrderBlock(
                        direction="BULLISH",
                        top=ob_top,
                        bottom=ob_bottom,
                        index=j,
                        timestamp=candles[j].timestamp,
                        mitigated=mitigated,
                        tested=tested,
                    ))
                    break

        # Strong bearish displacement
        if _is_bearish(c) and body >= atr * min_displacement_ratio:
            for j in range(i - 1, max(i - 4, -1), -1):
                if _is_bullish(candles[j]):
                    ob_top = candles[j].close  # body top of bullish = close
                    ob_bottom = candles[j].open  # body bottom = open
                    mitigated = any(
                        candles[k].high >= ob_bottom
                        for k in range(i + 1, len(candles))
                    )
                    tested = current_price >= ob_bottom and current_price <= ob_top
                    obs.append(OrderBlock(
                        direction="BEARISH",
                        top=ob_top,
                        bottom=ob_bottom,
                        index=j,
                        timestamp=candles[j].timestamp,
                        mitigated=mitigated,
                        tested=tested,
                    ))
                    break

    return obs


# ---------------------------------------------------------------------------
# Breaker Block detection
# ---------------------------------------------------------------------------


def detect_breaker_blocks(
    order_blocks: list[OrderBlock],
    candles: list[Candle],
) -> list[BreakerBlock]:
    """Detect breaker blocks (order blocks that failed and got mitigated).

    When a bullish OB gets broken (price closes below it), it becomes a
    bearish breaker block (now acts as resistance). And vice versa.
    """
    if not order_blocks or not candles:
        return []

    breakers: list[BreakerBlock] = []

    for ob in order_blocks:
        if not ob.mitigated:
            continue

        # Bullish OB broken = becomes bearish breaker
        if ob.direction == "BULLISH":
            # Check if price closed below the OB bottom
            broken = any(
                candles[k].close < ob.bottom
                for k in range(ob.index + 1, len(candles))
            )
            if broken:
                # Check if breaker has been mitigated (retested from below)
                re_mitigated = any(
                    candles[k].close > ob.top
                    for k in range(ob.index + 2, len(candles))
                )
                breakers.append(BreakerBlock(
                    direction="BEARISH",
                    top=ob.top,
                    bottom=ob.bottom,
                    index=ob.index,
                    timestamp=ob.timestamp,
                    mitigated=re_mitigated,
                ))

        # Bearish OB broken = becomes bullish breaker
        elif ob.direction == "BEARISH":
            broken = any(
                candles[k].close > ob.top
                for k in range(ob.index + 1, len(candles))
            )
            if broken:
                re_mitigated = any(
                    candles[k].close < ob.bottom
                    for k in range(ob.index + 2, len(candles))
                )
                breakers.append(BreakerBlock(
                    direction="BULLISH",
                    top=ob.top,
                    bottom=ob.bottom,
                    index=ob.index,
                    timestamp=ob.timestamp,
                    mitigated=re_mitigated,
                ))

    return breakers

