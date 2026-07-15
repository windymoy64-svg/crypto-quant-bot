"""Strategi Liquidity + S/R + Trend + Multi-Timeframe.

Implementasi kontrak section 7.2 di ``docs/strategy_liquidity_sr_mtf.md``.
Strategi ini pure dan deterministic. ``evaluate(mtf_context)`` mengonsumsi
tiga timeframe (big, mid, small) berupa list ``Candle`` dan mengembalikan
``StrategyDecision`` (BUY / SELL / HOLD) beserta anchor, level
entry/SL/TP, alasan deterministic, dan ringkasan trend MTF.

Aturan mutlak (hard-gate) di section 6 dokumen strategi diterapkan
sebagai early-return ``HOLD``:

- Trend TF besar wajib ``UP`` untuk BUY atau ``DOWN`` untuk SELL.
  ``SIDE`` selalu ``HOLD``.
- Harga saat ini harus berada di dalam zone S/R yang searah bias
  (support untuk BUY, resistance untuk SELL). Tanpa anchor => ``HOLD``.
- Liquidity pool anchor harus ``fresh`` (belum swept). Fresh pool
  prioritas mutlak per section 6.
- Wajib ada sweep event ``confirmed`` di TF menengah (bukan breakout).
- Wajib ada candle konfirmasi di TF kecil (engulfing atau pin bar
  searah bias).

Strategi tidak melakukan I/O, tidak menyentuh live execution, dan tidak
membaca / menulis file. Semua keputusan berbasis input candles.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from app.core.models import Candle
from app.indicators.liquidity_structure import (
    LiquidityPool,
    StructureState,
    SweepEvent,
    Zone,
    liquidity_pools,
    sr_zones,
    structure_state,
    sweep_events,
    swing_points,
)


Action = Literal["BUY", "SELL", "HOLD"]

DEFAULT_ZONE_TOLERANCE_PCT = 0.001  # 0.1%
DEFAULT_SL_BUFFER_PCT = 0.001       # 0.1% beyond the sweep wick
MIN_RR = 2.0                         # section 8: minimum risk:reward 1:2


@dataclass(frozen=True)
class MTFContext:
    """Container tiga lapis timeframe.

    ``big`` menentukan bias tren dan zone S/R utama. ``mid`` dipakai untuk
    deteksi sweep likuiditas. ``small`` dipakai untuk timing entry dan
    konfirmasi candle. Label timeframe (``big_tf`` dst.) hanya metadata
    untuk audit; tidak dipakai untuk logika.
    """

    big: list[Candle]
    mid: list[Candle]
    small: list[Candle]
    big_tf: str = "4h"
    mid_tf: str = "1h"
    small_tf: str = "5m"


@dataclass(frozen=True)
class MTFAlignment:
    big_trend: Literal["UP", "DOWN", "SIDE"]
    mid_trend: Literal["UP", "DOWN", "SIDE"]
    small_trend: Literal["UP", "DOWN", "SIDE"]
    aligned: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StrategyDecision:
    action: Action
    reasons: list[str]
    mtf_alignment: MTFAlignment
    anchor: dict[str, Any] | None = None
    entry: float | None = None
    stop_loss: float | None = None
    take_profit_1: float | None = None
    take_profit_2: float | None = None
    strategy: str = "liquidity_sr_mtf"
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["mtf_alignment"] = self.mtf_alignment.to_dict()
        return payload


# ---------------------------------------------------------------------------
# Candle pattern helpers (small TF confirmation)
# ---------------------------------------------------------------------------


def _is_bullish_engulfing(prev: Candle, curr: Candle) -> bool:
    prev_bearish = prev.close < prev.open
    curr_bullish = curr.close > curr.open
    engulf = curr.open <= prev.close and curr.close >= prev.open
    return prev_bearish and curr_bullish and engulf


def _is_bearish_engulfing(prev: Candle, curr: Candle) -> bool:
    prev_bullish = prev.close > prev.open
    curr_bearish = curr.close < curr.open
    engulf = curr.open >= prev.close and curr.close <= prev.open
    return prev_bullish and curr_bearish and engulf


def _is_bullish_pin_bar(candle: Candle) -> bool:
    body = abs(candle.close - candle.open)
    total = candle.high - candle.low
    if total <= 0:
        return False
    lower_wick = min(candle.open, candle.close) - candle.low
    upper_wick = candle.high - max(candle.open, candle.close)
    return (
        lower_wick >= 2 * body
        and lower_wick >= 2 * upper_wick
        and body / total <= 0.35
    )


def _is_bearish_pin_bar(candle: Candle) -> bool:
    body = abs(candle.close - candle.open)
    total = candle.high - candle.low
    if total <= 0:
        return False
    upper_wick = candle.high - max(candle.open, candle.close)
    lower_wick = min(candle.open, candle.close) - candle.low
    return (
        upper_wick >= 2 * body
        and upper_wick >= 2 * lower_wick
        and body / total <= 0.35
    )


def _bullish_confirmation(candles: list[Candle]) -> str | None:
    if len(candles) < 2:
        return None
    if _is_bullish_engulfing(candles[-2], candles[-1]):
        return "bullish_engulfing"
    if _is_bullish_pin_bar(candles[-1]):
        return "bullish_pin_bar"
    return None


def _bearish_confirmation(candles: list[Candle]) -> str | None:
    if len(candles) < 2:
        return None
    if _is_bearish_engulfing(candles[-2], candles[-1]):
        return "bearish_engulfing"
    if _is_bearish_pin_bar(candles[-1]):
        return "bearish_pin_bar"
    return None



# ---------------------------------------------------------------------------
# Zone / pool selection helpers
# ---------------------------------------------------------------------------


def _price_in_zone(price: float, zone: Zone, tolerance_pct: float) -> bool:
    """True if ``price`` sits inside ``zone`` (with a small % tolerance).

    The tolerance widens the zone symmetrically by ``tolerance_pct`` of the
    zone's mid price. It handles the common case where price prints a tick
    outside the zone right after a wick.
    """

    mid = (zone.price_low + zone.price_high) / 2
    pad = abs(mid) * tolerance_pct
    return (zone.price_low - pad) <= price <= (zone.price_high + pad)


def _nearest_active_zone(
    price: float,
    zones: list[Zone],
    kind: Literal["SUPPORT", "RESISTANCE"],
    tolerance_pct: float,
) -> Zone | None:
    """Pick the nearest unmitigated zone that contains ``price``."""

    candidates = [z for z in zones if z.kind == kind and not z.mitigated]
    active = [z for z in candidates if _price_in_zone(price, z, tolerance_pct)]
    if not active:
        return None
    active.sort(
        key=lambda z: abs(price - (z.price_low + z.price_high) / 2)
    )
    return active[0]


def _last_confirmed_sweep(
    events: list[SweepEvent],
    side: Literal["BUY_SIDE", "SELL_SIDE"],
) -> SweepEvent | None:
    matches = [e for e in events if e.pool_side == side and e.confirmed]
    if not matches:
        return None
    return max(matches, key=lambda e: e.sweep_index)


def _fresh_pool_beyond(
    pools: list[LiquidityPool],
    side: Literal["BUY_SIDE", "SELL_SIDE"],
    reference_price: float,
) -> LiquidityPool | None:
    """Find a fresh pool that could still be swept in the trade direction.

    - For ``SELL_SIDE`` in an UP trend: fresh sell-side pool sitting *at or
      below* the reference price (deeper liquidity yet to be swept).
    - For ``BUY_SIDE`` in a DOWN trend: fresh buy-side pool sitting *at or
      above* the reference price.
    """

    if side == "SELL_SIDE":
        candidates = [
            p for p in pools if p.fresh and p.price <= reference_price
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda p: p.price)
    candidates = [p for p in pools if p.fresh and p.price >= reference_price]
    if not candidates:
        return None
    return min(candidates, key=lambda p: p.price)



# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _hold(
    reason: str,
    alignment: MTFAlignment,
    extra_reasons: list[str] | None = None,
) -> StrategyDecision:
    reasons = [reason]
    if extra_reasons:
        reasons.extend(extra_reasons)
    return StrategyDecision(
        action="HOLD",
        reasons=reasons,
        mtf_alignment=alignment,
        meta={"veto": reason},
    )


def _compute_alignment(
    big: StructureState, mid: StructureState, small: StructureState
) -> MTFAlignment:
    aligned = big.trend != "SIDE" and big.trend == mid.trend
    return MTFAlignment(
        big_trend=big.trend,
        mid_trend=mid.trend,
        small_trend=small.trend,
        aligned=aligned,
    )


def evaluate(
    ctx: MTFContext,
    *,
    zone_tolerance_pct: float = DEFAULT_ZONE_TOLERANCE_PCT,
    sl_buffer_pct: float = DEFAULT_SL_BUFFER_PCT,
    min_rr: float = MIN_RR,
) -> StrategyDecision:
    """Evaluate the strategy against a three-timeframe context.

    Returns ``HOLD`` when any mandatory rule (section 6 of the spec) fails.
    Returns ``BUY`` / ``SELL`` with anchor, entry, SL, TP1, TP2 and a list
    of deterministic reasons when every hard-gate passes.
    """

    if not ctx.big or not ctx.mid or not ctx.small:
        empty_alignment = MTFAlignment("SIDE", "SIDE", "SIDE", False)
        return _hold("empty_candles", empty_alignment)

    big_swings = swing_points(ctx.big)
    mid_swings = swing_points(ctx.mid)
    small_swings = swing_points(ctx.small)
    big_state = structure_state(big_swings)
    mid_state = structure_state(mid_swings)
    small_state = structure_state(small_swings)
    alignment = _compute_alignment(big_state, mid_state, small_state)

    if big_state.trend == "SIDE":
        return _hold("big_tf_trend_side", alignment)

    current_price = ctx.small[-1].close
    zones = sr_zones(ctx.big, big_swings)
    pools = liquidity_pools(ctx.mid, mid_swings)
    events = sweep_events(ctx.mid, pools)
    base_reasons: list[str] = [f"big_tf_trend_{big_state.trend.lower()}"]

    if big_state.trend == "UP":
        return _evaluate_long(
            ctx=ctx,
            current_price=current_price,
            zones=zones,
            pools=pools,
            events=events,
            alignment=alignment,
            base_reasons=base_reasons,
            zone_tolerance_pct=zone_tolerance_pct,
            sl_buffer_pct=sl_buffer_pct,
            min_rr=min_rr,
        )
    return _evaluate_short(
        ctx=ctx,
        current_price=current_price,
        zones=zones,
        pools=pools,
        events=events,
        alignment=alignment,
        base_reasons=base_reasons,
        zone_tolerance_pct=zone_tolerance_pct,
        sl_buffer_pct=sl_buffer_pct,
        min_rr=min_rr,
    )



# ---------------------------------------------------------------------------
# Long / short evaluators
# ---------------------------------------------------------------------------


def _evaluate_long(
    *,
    ctx: MTFContext,
    current_price: float,
    zones: list[Zone],
    pools: list[LiquidityPool],
    events: list[SweepEvent],
    alignment: MTFAlignment,
    base_reasons: list[str],
    zone_tolerance_pct: float,
    sl_buffer_pct: float,
    min_rr: float,
) -> StrategyDecision:
    # Hard-gate 2: price must sit inside a fresh support zone (anchor S/R).
    support = _nearest_active_zone(
        current_price, zones, "SUPPORT", zone_tolerance_pct
    )
    if support is None:
        return _hold("no_active_support_zone", alignment, base_reasons)

    # Hard-gate 3: a sell-side liquidity sweep must have been confirmed
    # (a real liquidity grab, not a breakout) on the mid TF.
    sweep = _last_confirmed_sweep(events, "SELL_SIDE")
    if sweep is None:
        return _hold("no_confirmed_sell_side_sweep", alignment, base_reasons)

    # Hard-gate 4: fresh liquidity must remain elsewhere as target/edge.
    fresh_target_pool = _fresh_pool_beyond(pools, "BUY_SIDE", current_price)
    if fresh_target_pool is None:
        return _hold("no_fresh_buy_side_target", alignment, base_reasons)

    # Hard-gate 5: small TF must print a bullish confirmation.
    confirmation = _bullish_confirmation(ctx.small)
    if confirmation is None:
        return _hold("no_small_tf_confirmation", alignment, base_reasons)

    # Levels ---------------------------------------------------------------
    entry = current_price
    sl_anchor = min(sweep.wick_price, support.price_low)
    stop_loss = sl_anchor * (1 - sl_buffer_pct)
    risk = entry - stop_loss
    if risk <= 0:
        return _hold("invalid_risk_non_positive", alignment, base_reasons)

    # TP1 = nearest resistance zone above entry (unmitigated). TP2 = fresh
    # buy-side pool above. Enforce minimum 1:2 RR on TP1.
    resistance_targets = [
        z
        for z in zones
        if z.kind == "RESISTANCE"
        and not z.mitigated
        and z.price_low > entry
    ]
    resistance_targets.sort(key=lambda z: z.price_low)
    tp1_candidate = (
        resistance_targets[0].price_low
        if resistance_targets
        else entry + risk * min_rr
    )
    tp1 = max(tp1_candidate, entry + risk * min_rr)
    tp2 = max(fresh_target_pool.price, tp1 + risk)

    reasons = list(base_reasons) + [
        "price_in_support_zone",
        "sell_side_liquidity_swept_confirmed",
        f"small_tf_confirmation_{confirmation}",
        "fresh_buy_side_target_available",
        f"rr_at_least_{min_rr:.1f}",
    ]
    if alignment.aligned:
        reasons.append("mid_tf_trend_aligned")

    anchor = {
        "support_zone": support.to_dict(),
        "sweep_event": sweep.to_dict(),
        "fresh_target_pool": fresh_target_pool.to_dict(),
    }
    meta = {
        "confirmation_pattern": confirmation,
        "risk": risk,
        "sl_anchor": sl_anchor,
    }
    return StrategyDecision(
        action="BUY",
        reasons=reasons,
        mtf_alignment=alignment,
        anchor=anchor,
        entry=entry,
        stop_loss=stop_loss,
        take_profit_1=tp1,
        take_profit_2=tp2,
        meta=meta,
    )



def _evaluate_short(
    *,
    ctx: MTFContext,
    current_price: float,
    zones: list[Zone],
    pools: list[LiquidityPool],
    events: list[SweepEvent],
    alignment: MTFAlignment,
    base_reasons: list[str],
    zone_tolerance_pct: float,
    sl_buffer_pct: float,
    min_rr: float,
) -> StrategyDecision:
    # Hard-gate 2: price must sit inside a fresh resistance zone.
    resistance = _nearest_active_zone(
        current_price, zones, "RESISTANCE", zone_tolerance_pct
    )
    if resistance is None:
        return _hold("no_active_resistance_zone", alignment, base_reasons)

    # Hard-gate 3: a buy-side liquidity sweep must have been confirmed.
    sweep = _last_confirmed_sweep(events, "BUY_SIDE")
    if sweep is None:
        return _hold("no_confirmed_buy_side_sweep", alignment, base_reasons)

    # Hard-gate 4: fresh sell-side liquidity must remain below as target.
    fresh_target_pool = _fresh_pool_beyond(pools, "SELL_SIDE", current_price)
    if fresh_target_pool is None:
        return _hold("no_fresh_sell_side_target", alignment, base_reasons)

    # Hard-gate 5: small TF must print a bearish confirmation.
    confirmation = _bearish_confirmation(ctx.small)
    if confirmation is None:
        return _hold("no_small_tf_confirmation", alignment, base_reasons)

    # Levels ---------------------------------------------------------------
    entry = current_price
    sl_anchor = max(sweep.wick_price, resistance.price_high)
    stop_loss = sl_anchor * (1 + sl_buffer_pct)
    risk = stop_loss - entry
    if risk <= 0:
        return _hold("invalid_risk_non_positive", alignment, base_reasons)

    support_targets = [
        z
        for z in zones
        if z.kind == "SUPPORT"
        and not z.mitigated
        and z.price_high < entry
    ]
    support_targets.sort(key=lambda z: z.price_high, reverse=True)
    tp1_candidate = (
        support_targets[0].price_high
        if support_targets
        else entry - risk * min_rr
    )
    tp1 = min(tp1_candidate, entry - risk * min_rr)
    tp2 = min(fresh_target_pool.price, tp1 - risk)

    reasons = list(base_reasons) + [
        "price_in_resistance_zone",
        "buy_side_liquidity_swept_confirmed",
        f"small_tf_confirmation_{confirmation}",
        "fresh_sell_side_target_available",
        f"rr_at_least_{min_rr:.1f}",
    ]
    if alignment.aligned:
        reasons.append("mid_tf_trend_aligned")

    anchor = {
        "resistance_zone": resistance.to_dict(),
        "sweep_event": sweep.to_dict(),
        "fresh_target_pool": fresh_target_pool.to_dict(),
    }
    meta = {
        "confirmation_pattern": confirmation,
        "risk": risk,
        "sl_anchor": sl_anchor,
    }
    return StrategyDecision(
        action="SELL",
        reasons=reasons,
        mtf_alignment=alignment,
        anchor=anchor,
        entry=entry,
        stop_loss=stop_loss,
        take_profit_1=tp1,
        take_profit_2=tp2,
        meta=meta,
    )

