"""Professional entry-zone / invalidation placement (structure + ATR).

Used by ChartReaderAgent. Not a trade decision — only level geometry.
"""

from __future__ import annotations

from typing import Any

from app.chart_agent.models import BiasDirection, KeyLevel, OrderBlock, TechniqueSignal
from app.core.models import Candle
from app.indicators.technical import atr as compute_atr

MIN_SL_ATR = 0.8
MAX_SL_ATR = 3.5
MIN_SL_PCT = 0.35
MAX_SL_PCT = 4.0
SL_BUFFER_ATR = 0.35
SL_BUFFER_PCT = 0.15
MAX_ZONE_DIST_PCT = 3.5


def sl_buffer(price: float, atr_value: float) -> float:
    return max(atr_value * SL_BUFFER_ATR, price * (SL_BUFFER_PCT / 100.0))


def harden_invalidation(
    *,
    bias: BiasDirection,
    structure_edge: float,
    entry_ref: float,
    atr_value: float,
) -> float | None:
    """Place SL beyond structure edge with ATR buffer; side-aware."""
    if entry_ref <= 0 or structure_edge <= 0:
        return None
    buf = sl_buffer(entry_ref, atr_value)
    if bias == "BULLISH":
        if structure_edge >= entry_ref:
            return None
        return structure_edge - buf
    if bias == "BEARISH":
        if structure_edge <= entry_ref:
            return None
        return structure_edge + buf
    return None


def sl_metrics(entry: float, stop: float, atr_value: float) -> dict[str, float]:
    risk = abs(entry - stop)
    atr_safe = atr_value if atr_value > 0 else entry * 0.01
    return {
        "risk": risk,
        "sl_pct": (risk / entry) * 100.0 if entry > 0 else 0.0,
        "sl_atr": risk / atr_safe if atr_safe > 0 else 0.0,
    }


def sl_passes_noise_floor(entry: float, stop: float, atr_value: float) -> bool:
    m = sl_metrics(entry, stop, atr_value)
    if m["sl_pct"] < MIN_SL_PCT and m["sl_atr"] < MIN_SL_ATR:
        return False
    if m["sl_atr"] < MIN_SL_ATR and m["sl_pct"] < MIN_SL_PCT * 1.5:
        return False
    if m["sl_pct"] > MAX_SL_PCT and m["sl_atr"] > MAX_SL_ATR:
        return False
    return True


def htf_targets(
    *,
    bias: BiasDirection,
    entry: float,
    htf_candles: list[Candle],
    mtf_candles: list[Candle],
    key_levels: list[KeyLevel],
) -> list[float]:
    """Structural targets beyond entry (swing / S-R), sorted trade direction."""
    targets: list[float] = []
    for candles in (htf_candles, mtf_candles):
        if len(candles) < 5:
            continue
        window = candles[-40:] if len(candles) >= 40 else candles
        swing_high = max(c.high for c in window)
        swing_low = min(c.low for c in window)
        if bias == "BULLISH" and swing_high > entry:
            targets.append(swing_high)
        if bias == "BEARISH" and swing_low < entry:
            targets.append(swing_low)
    for level in key_levels:
        if bias == "BULLISH" and level.kind == "resistance" and level.price > entry:
            targets.append(level.price)
        if bias == "BEARISH" and level.kind == "support" and level.price < entry:
            targets.append(level.price)
    uniq = sorted(set(round(t, 8) for t in targets))
    if bias == "BULLISH":
        return [t for t in uniq if t > entry]
    if bias == "BEARISH":
        return [t for t in reversed(uniq) if t < entry]
    return []


def atr_from_candles(candles: list[Candle], price: float) -> float:
    value = compute_atr(candles, 14) if candles else 0.0
    if value <= 0:
        return price * 0.01 if price > 0 else 0.0
    return value



def select_entry_invalidation(
    *,
    bias: BiasDirection,
    current_price: float,
    atr_value: float,
    liq_signal: TechniqueSignal,
    obs: list[OrderBlock],
    key_levels: list[KeyLevel],
    htf_candles: list[Candle],
    mtf_candles: list[Candle],
    ltf_candles: list[Candle],
) -> tuple[tuple[float, float] | None, float | None, str | None, dict[str, Any]]:
    """Pick structure-based zone + SL that clears the noise floor."""
    meta: dict[str, Any] = {"atr": round(atr_value, 8), "candidates_evaluated": 0}
    if bias == "NEUTRAL" or current_price <= 0:
        return None, None, None, meta

    candidates: list[tuple[tuple[float, float], float, str, float]] = []

    if liq_signal.meta.get("entry") and liq_signal.meta.get("stop_loss"):
        entry_price = float(liq_signal.meta["entry"])
        raw_sl = float(liq_signal.meta["stop_loss"])
        zone = (min(entry_price, raw_sl), max(entry_price, raw_sl))
        hardened = harden_invalidation(
            bias=bias, structure_edge=raw_sl, entry_ref=entry_price, atr_value=atr_value
        )
        if hardened is not None:
            candidates.append((zone, hardened, "liquidity_sr", 0.0))

    for ob in obs:
        if ob.mitigated:
            continue
        if bias == "BULLISH" and ob.direction == "BULLISH" and ob.top <= current_price * 1.002:
            zone = (ob.bottom, ob.top)
            hardened = harden_invalidation(
                bias=bias,
                structure_edge=ob.bottom,
                entry_ref=(ob.bottom + ob.top) / 2,
                atr_value=atr_value,
            )
            if hardened is not None:
                candidates.append((zone, hardened, "order_block_BULLISH", 0.5))
        if bias == "BEARISH" and ob.direction == "BEARISH" and ob.bottom >= current_price * 0.998:
            zone = (ob.bottom, ob.top)
            hardened = harden_invalidation(
                bias=bias,
                structure_edge=ob.top,
                entry_ref=(ob.bottom + ob.top) / 2,
                atr_value=atr_value,
            )
            if hardened is not None:
                candidates.append((zone, hardened, "order_block_BEARISH", 0.5))

    for level in key_levels:
        if bias == "BULLISH" and level.kind == "support" and level.price <= current_price:
            width = max(atr_value * 0.25, current_price * 0.0015)
            zone = (level.price - width * 0.25, level.price + width)
            hardened = harden_invalidation(
                bias=bias,
                structure_edge=level.price,
                entry_ref=level.price,
                atr_value=atr_value,
            )
            if hardened is not None:
                candidates.append((zone, hardened, f"key_level_{level.source}", 1.0))
        if bias == "BEARISH" and level.kind == "resistance" and level.price >= current_price:
            width = max(atr_value * 0.25, current_price * 0.0015)
            zone = (level.price - width, level.price + width * 0.25)
            hardened = harden_invalidation(
                bias=bias,
                structure_edge=level.price,
                entry_ref=level.price,
                atr_value=atr_value,
            )
            if hardened is not None:
                candidates.append((zone, hardened, f"key_level_{level.source}", 1.0))

    return _rank_candidates(
        candidates=candidates,
        meta=meta,
        bias=bias,
        current_price=current_price,
        atr_value=atr_value,
        htf_candles=htf_candles,
        mtf_candles=mtf_candles,
        ltf_candles=ltf_candles,
        key_levels=key_levels,
    )


def _rank_candidates(
    *,
    candidates: list[tuple[tuple[float, float], float, str, float]],
    meta: dict[str, Any],
    bias: BiasDirection,
    current_price: float,
    atr_value: float,
    htf_candles: list[Candle],
    mtf_candles: list[Candle],
    ltf_candles: list[Candle],
    key_levels: list[KeyLevel],
) -> tuple[tuple[float, float] | None, float | None, str | None, dict[str, Any]]:
    # Always include swing anchors so noise OB/key-level candidates cannot
    # starve the ranking when they all fail the noise floor.
    for label, candles in (("ltf_swing", ltf_candles), ("mtf_swing", mtf_candles)):
        if len(candles) < 10:
            continue
        window = candles[-30:] if len(candles) >= 30 else candles
        swing_low = min(c.low for c in window)
        swing_high = max(c.high for c in window)
        if bias == "BULLISH" and swing_low < current_price:
            hardened = harden_invalidation(
                bias=bias,
                structure_edge=swing_low,
                entry_ref=current_price,
                atr_value=atr_value,
            )
            if hardened is not None:
                candidates.append(((swing_low, current_price), hardened, label, 1.5))
        if bias == "BEARISH" and swing_high > current_price:
            hardened = harden_invalidation(
                bias=bias,
                structure_edge=swing_high,
                entry_ref=current_price,
                atr_value=atr_value,
            )
            if hardened is not None:
                candidates.append(((current_price, swing_high), hardened, label, 1.5))

    meta["candidates_evaluated"] = len(candidates)
    if not candidates:
        meta["reject"] = "no_structure_candidates"
        return None, None, None, meta

    ranked: list[tuple[float, tuple[float, float], float, str]] = []
    for zone, inval, source, source_penalty in candidates:
        mid = (zone[0] + zone[1]) / 2
        entry_ref = mid if mid > 0 else current_price
        if zone[0] <= current_price <= zone[1]:
            entry_ref = current_price
        dist_pct = abs(mid - current_price) / current_price * 100.0
        if dist_pct > MAX_ZONE_DIST_PCT:
            continue
        if not sl_passes_noise_floor(entry_ref, inval, atr_value):
            continue
        m = sl_metrics(entry_ref, inval, atr_value)
        score = abs(m["sl_atr"] - 1.5) + dist_pct * 0.15 + source_penalty
        ranked.append((score, zone, inval, source))

    if not ranked:
        meta["reject"] = "no_candidate_cleared_noise_floor"
        return None, None, None, meta

    ranked.sort(key=lambda item: item[0])
    _score, entry_zone, invalidation, source = ranked[0]
    zone_mid = (entry_zone[0] + entry_zone[1]) / 2
    entry_ref = (
        current_price if entry_zone[0] <= current_price <= entry_zone[1] else zone_mid
    )
    m = sl_metrics(entry_ref, invalidation, atr_value)
    targets = htf_targets(
        bias=bias,
        entry=entry_ref,
        htf_candles=htf_candles,
        mtf_candles=mtf_candles,
        key_levels=key_levels,
    )
    meta.update(
        {
            "source": source,
            "sl_pct": round(m["sl_pct"], 3),
            "sl_atr": round(m["sl_atr"], 3),
            "zone_dist_pct": round(
                abs(zone_mid - current_price) / current_price * 100.0, 3
            ),
            "targets": targets[:5],
            "target_primary": targets[0] if targets else None,
        }
    )
    return entry_zone, invalidation, source, meta

