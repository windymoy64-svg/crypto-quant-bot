from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from app.core.models import Candle


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


SwingKind = Literal["HH", "HL", "LH", "LL"]
Trend = Literal["UP", "DOWN", "SIDE"]
ZoneKind = Literal["SUPPORT", "RESISTANCE"]
LiquiditySide = Literal["BUY_SIDE", "SELL_SIDE"]


@dataclass(frozen=True)
class SwingPoint:
    """Deterministic fractal swing point.

    ``kind`` classifies the swing relative to the previous same-side swing:
    - Swing highs are ``HH`` when higher than the previous swing high,
      otherwise ``LH``.
    - Swing lows are ``HL`` when higher than the previous swing low,
      otherwise ``LL``.
    - The very first swing on each side defaults to ``HH`` / ``HL`` because
      there is no earlier reference; downstream logic should treat these as
      neutral seeds.
    """

    index: int
    timestamp: str
    price: float
    kind: SwingKind
    side: Literal["HIGH", "LOW"]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StructureState:
    trend: Trend
    last_bos: SwingPoint | None
    last_choch: SwingPoint | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "trend": self.trend,
            "last_bos": self.last_bos.to_dict() if self.last_bos else None,
            "last_choch": self.last_choch.to_dict() if self.last_choch else None,
        }


@dataclass(frozen=True)
class Zone:
    kind: ZoneKind
    price_low: float
    price_high: float
    touches: int
    mitigated: bool
    anchor_indices: tuple[int, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["anchor_indices"] = list(self.anchor_indices)
        return data

    def contains(self, price: float) -> bool:
        return self.price_low <= price <= self.price_high


@dataclass(frozen=True)
class LiquidityPool:
    side: LiquiditySide
    price: float
    created_at: str
    created_index: int
    swept: bool
    fresh: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SweepEvent:
    pool_side: LiquiditySide
    pool_price: float
    pool_created_index: int
    sweep_index: int
    sweep_timestamp: str
    wick_price: float
    close_price: float
    confirmed: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Swing detection and structure
# ---------------------------------------------------------------------------


def swing_points(
    candles: list[Candle],
    left: int = 2,
    right: int = 2,
) -> list[SwingPoint]:
    """Detect swing highs and lows using a symmetric fractal window.

    A candle at index ``i`` is a swing high when its ``high`` is strictly
    greater than every ``high`` in ``candles[i-left:i]`` and every ``high``
    in ``candles[i+1:i+1+right]``. Swing lows use the mirror rule on ``low``.

    Each swing is classified deterministically (``HH``/``LH`` for highs,
    ``HL``/``LL`` for lows) by comparing it to the most recent swing of the
    same side. The very first swing on each side is seeded as ``HH``/``HL``.
    """

    if left < 1 or right < 1:
        raise ValueError("left and right must be >= 1")
    if len(candles) < left + right + 1:
        return []

    raw: list[tuple[int, str, float, Literal["HIGH", "LOW"]]] = []
    for i in range(left, len(candles) - right):
        center = candles[i]
        window_left = candles[i - left : i]
        window_right = candles[i + 1 : i + 1 + right]
        if all(center.high > c.high for c in window_left) and all(
            center.high > c.high for c in window_right
        ):
            raw.append((i, center.timestamp, center.high, "HIGH"))
        if all(center.low < c.low for c in window_left) and all(
            center.low < c.low for c in window_right
        ):
            raw.append((i, center.timestamp, center.low, "LOW"))

    raw.sort(key=lambda item: item[0])

    swings: list[SwingPoint] = []
    last_high_price: float | None = None
    last_low_price: float | None = None
    for index, timestamp, price, side in raw:
        if side == "HIGH":
            kind: SwingKind = (
                "HH" if last_high_price is None or price > last_high_price else "LH"
            )
            last_high_price = price
        else:
            kind = "HL" if last_low_price is None or price > last_low_price else "LL"
            last_low_price = price
        swings.append(
            SwingPoint(
                index=index,
                timestamp=timestamp,
                price=price,
                kind=kind,
                side=side,
            )
        )
    return swings


def structure_state(swings: list[SwingPoint]) -> StructureState:
    """Summarise trend, last Break of Structure, and last Change of Character.

    Trend rule:
    - ``UP`` when the last swing high is ``HH`` and the last swing low is ``HL``.
    - ``DOWN`` when the last swing high is ``LH`` and the last swing low is ``LL``.
    - ``SIDE`` otherwise (mixed or insufficient swings).

    BOS is the most recent swing that confirmed the current trend
    (``HH`` in ``UP``, ``LL`` in ``DOWN``). CHoCH is the most recent swing
    that contradicts the current trend (``LH`` in ``UP``, ``HH`` in ``DOWN``);
    in ``SIDE`` it is ``None``.
    """

    if not swings:
        return StructureState(trend="SIDE", last_bos=None, last_choch=None)

    last_high = next((s for s in reversed(swings) if s.side == "HIGH"), None)
    last_low = next((s for s in reversed(swings) if s.side == "LOW"), None)

    trend: Trend = "SIDE"
    if last_high and last_low:
        if last_high.kind == "HH" and last_low.kind == "HL":
            trend = "UP"
        elif last_high.kind == "LH" and last_low.kind == "LL":
            trend = "DOWN"

    last_bos: SwingPoint | None = None
    last_choch: SwingPoint | None = None
    if trend == "UP":
        last_bos = next((s for s in reversed(swings) if s.kind == "HH"), None)
        last_choch = next((s for s in reversed(swings) if s.kind == "LH"), None)
    elif trend == "DOWN":
        last_bos = next((s for s in reversed(swings) if s.kind == "LL"), None)
        last_choch = next((s for s in reversed(swings) if s.kind == "HH"), None)

    return StructureState(trend=trend, last_bos=last_bos, last_choch=last_choch)


# ---------------------------------------------------------------------------
# S/R zones
# ---------------------------------------------------------------------------


def _zone_bounds(candle: Candle, side: Literal["HIGH", "LOW"]) -> tuple[float, float]:
    """Zone bounds are anchored to the candle body around the swing wick.

    For a swing high the zone spans from ``max(open, close)`` to ``high``.
    For a swing low the zone spans from ``low`` to ``min(open, close)``.
    This keeps the zone deterministic and dependent only on the swing candle
    itself, without any ATR or volatility parameter that could drift.
    """

    if side == "HIGH":
        upper = candle.high
        lower = max(candle.open, candle.close)
        if lower >= upper:
            lower = upper - abs(upper - candle.low) * 0.5
        return lower, upper
    lower = candle.low
    upper = min(candle.open, candle.close)
    if upper <= lower:
        upper = lower + abs(candle.high - lower) * 0.5
    return lower, upper


def sr_zones(candles: list[Candle], swings: list[SwingPoint]) -> list[Zone]:
    """Build support and resistance zones from swing points.

    Every swing high becomes a resistance zone anchor and every swing low
    becomes a support zone anchor. Overlapping zones of the same kind are
    merged and their ``touches`` counter is incremented. A zone is marked
    ``mitigated`` when any candle *after* the last anchor closes on the wrong
    side of the zone body:

    - Support: a later candle closes below ``price_low``.
    - Resistance: a later candle closes above ``price_high``.
    """

    if not swings:
        return []

    raw_zones: list[tuple[ZoneKind, float, float, int]] = []
    for swing in swings:
        candle = candles[swing.index]
        if swing.side == "HIGH":
            low, high = _zone_bounds(candle, "HIGH")
            raw_zones.append(("RESISTANCE", low, high, swing.index))
        else:
            low, high = _zone_bounds(candle, "LOW")
            raw_zones.append(("SUPPORT", low, high, swing.index))

    merged: list[dict[str, Any]] = []
    for kind, low, high, idx in raw_zones:
        placed = False
        for zone in merged:
            if zone["kind"] != kind:
                continue
            if low <= zone["price_high"] and high >= zone["price_low"]:
                zone["price_low"] = min(zone["price_low"], low)
                zone["price_high"] = max(zone["price_high"], high)
                zone["touches"] += 1
                zone["anchor_indices"].append(idx)
                placed = True
                break
        if not placed:
            merged.append(
                {
                    "kind": kind,
                    "price_low": low,
                    "price_high": high,
                    "touches": 1,
                    "anchor_indices": [idx],
                }
            )

    zones: list[Zone] = []
    for zone in merged:
        last_anchor = max(zone["anchor_indices"])
        mitigated = False
        for later in candles[last_anchor + 1 :]:
            if zone["kind"] == "SUPPORT" and later.close < zone["price_low"]:
                mitigated = True
                break
            if zone["kind"] == "RESISTANCE" and later.close > zone["price_high"]:
                mitigated = True
                break
        zones.append(
            Zone(
                kind=zone["kind"],
                price_low=zone["price_low"],
                price_high=zone["price_high"],
                touches=zone["touches"],
                mitigated=mitigated,
                anchor_indices=tuple(sorted(zone["anchor_indices"])),
            )
        )

    zones.sort(key=lambda z: (z.kind, z.price_low))
    return zones



    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Liquidity pools and sweep events
# ---------------------------------------------------------------------------


def liquidity_pools(
    candles: list[Candle], swings: list[SwingPoint]
) -> list[LiquidityPool]:
    """Build buy-side and sell-side liquidity pools from swings.

    - Every swing high creates a ``BUY_SIDE`` pool at ``swing.price`` because
      stop-losses of shorts and breakout buy orders cluster above the swing.
    - Every swing low creates a ``SELL_SIDE`` pool at ``swing.price`` because
      stop-losses of longs and breakout sell orders cluster below the swing.

    A pool is ``swept`` (and therefore not ``fresh``) when a later candle's
    wick reaches through the pool price:

    - BUY_SIDE swept when a later ``candle.high >= pool.price``.
    - SELL_SIDE swept when a later ``candle.low <= pool.price``.
    """

    pools: list[LiquidityPool] = []
    for swing in swings:
        side: LiquiditySide = "BUY_SIDE" if swing.side == "HIGH" else "SELL_SIDE"
        swept = False
        for later in candles[swing.index + 1 :]:
            if side == "BUY_SIDE" and later.high >= swing.price:
                swept = True
                break
            if side == "SELL_SIDE" and later.low <= swing.price:
                swept = True
                break
        pools.append(
            LiquidityPool(
                side=side,
                price=swing.price,
                created_at=swing.timestamp,
                created_index=swing.index,
                swept=swept,
                fresh=not swept,
            )
        )
    return pools


def sweep_events(
    candles: list[Candle], pools: list[LiquidityPool]
) -> list[SweepEvent]:
    """Emit one sweep event per swept pool.

    For each swept pool, find the first candle after ``created_index`` whose
    wick crossed the pool price. The event records that candle's extreme
    wick, its close, and whether the sweep is ``confirmed``.

    A sweep is ``confirmed`` when the close of the sweeping candle returns
    to the origin side of the pool (i.e. the wick pierced but the body did
    not close beyond the level). This distinguishes a liquidity grab from
    a genuine breakout, per the strategy spec section 5.

    - BUY_SIDE pool: confirmed when ``candle.high >= pool.price`` and
      ``candle.close < pool.price``.
    - SELL_SIDE pool: confirmed when ``candle.low <= pool.price`` and
      ``candle.close > pool.price``.

    Fresh (not swept) pools produce no event.
    """

    events: list[SweepEvent] = []
    for pool in pools:
        if not pool.swept:
            continue
        for later_index in range(pool.created_index + 1, len(candles)):
            later = candles[later_index]
            hit = (
                (pool.side == "BUY_SIDE" and later.high >= pool.price)
                or (pool.side == "SELL_SIDE" and later.low <= pool.price)
            )
            if not hit:
                continue
            if pool.side == "BUY_SIDE":
                wick_price = later.high
                confirmed = later.close < pool.price
            else:
                wick_price = later.low
                confirmed = later.close > pool.price
            events.append(
                SweepEvent(
                    pool_side=pool.side,
                    pool_price=pool.price,
                    pool_created_index=pool.created_index,
                    sweep_index=later_index,
                    sweep_timestamp=later.timestamp,
                    wick_price=wick_price,
                    close_price=later.close,
                    confirmed=confirmed,
                )
            )
            break
    return events

