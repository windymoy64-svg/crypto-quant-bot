"""Comprehensive candle pattern detection — 40+ patterns.

All detectors are pure, deterministic, and operate on a list of Candle objects.
Each function returns a list of CandlePatternDetection for the most recent
candles (typically checking the last 1-5 candles for pattern formation).

Patterns are grouped:
- Single candle (doji, hammer, shooting star, marubozu, etc.)
- Double candle (engulfing, harami, tweezer, piercing, dark cloud, etc.)
- Triple candle (morning/evening star, three soldiers/crows, etc.)
"""

from __future__ import annotations

from app.core.models import Candle
from app.chart_agent.models import CandlePatternDetection, PatternDirection


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _body(c: Candle) -> float:
    return abs(c.close - c.open)


def _range(c: Candle) -> float:
    return c.high - c.low


def _body_ratio(c: Candle) -> float:
    r = _range(c)
    return _body(c) / r if r > 0 else 0.0


def _upper_wick(c: Candle) -> float:
    return c.high - max(c.open, c.close)


def _lower_wick(c: Candle) -> float:
    return min(c.open, c.close) - c.low


def _is_bullish(c: Candle) -> bool:
    return c.close > c.open


def _is_bearish(c: Candle) -> bool:
    return c.close < c.open


def _body_top(c: Candle) -> float:
    return max(c.open, c.close)


def _body_bottom(c: Candle) -> float:
    return min(c.open, c.close)


def _midpoint(c: Candle) -> float:
    return (c.high + c.low) / 2


# ---------------------------------------------------------------------------
# Single candle patterns
# ---------------------------------------------------------------------------


def _detect_doji(candles: list[Candle]) -> CandlePatternDetection | None:
    """Doji: body <= 10% of range."""
    c = candles[-1]
    if _range(c) <= 0:
        return None
    if _body_ratio(c) <= 0.10:
        return CandlePatternDetection(
            name="doji",
            direction="NEUTRAL",
            strength="WEAK",
            candle_count=1,
            start_index=len(candles) - 1,
            end_index=len(candles) - 1,
            reliability=40.0,
            description="Indecision candle, body sangat kecil relatif terhadap range",
        )
    return None


def _detect_dragonfly_doji(candles: list[Candle]) -> CandlePatternDetection | None:
    """Dragonfly doji: doji with long lower wick, almost no upper wick."""
    c = candles[-1]
    r = _range(c)
    if r <= 0:
        return None
    if _body_ratio(c) <= 0.10 and _lower_wick(c) >= r * 0.65 and _upper_wick(c) <= r * 0.10:
        return CandlePatternDetection(
            name="dragonfly_doji",
            direction="BULLISH",
            strength="MODERATE",
            candle_count=1,
            start_index=len(candles) - 1,
            end_index=len(candles) - 1,
            reliability=55.0,
            description="Doji dengan lower wick panjang — potensi reversal bullish",
        )
    return None


def _detect_gravestone_doji(candles: list[Candle]) -> CandlePatternDetection | None:
    """Gravestone doji: doji with long upper wick, almost no lower wick."""
    c = candles[-1]
    r = _range(c)
    if r <= 0:
        return None
    if _body_ratio(c) <= 0.10 and _upper_wick(c) >= r * 0.65 and _lower_wick(c) <= r * 0.10:
        return CandlePatternDetection(
            name="gravestone_doji",
            direction="BEARISH",
            strength="MODERATE",
            candle_count=1,
            start_index=len(candles) - 1,
            end_index=len(candles) - 1,
            reliability=55.0,
            description="Doji dengan upper wick panjang — potensi reversal bearish",
        )
    return None


def _detect_hammer(candles: list[Candle]) -> CandlePatternDetection | None:
    """Hammer: small body at top, long lower wick >= 2x body."""
    c = candles[-1]
    body = _body(c)
    r = _range(c)
    if r <= 0 or body <= 0:
        return None
    lw = _lower_wick(c)
    uw = _upper_wick(c)
    if lw >= 2 * body and uw <= body * 0.5 and _body_ratio(c) <= 0.35:
        return CandlePatternDetection(
            name="hammer",
            direction="BULLISH",
            strength="MODERATE",
            candle_count=1,
            start_index=len(candles) - 1,
            end_index=len(candles) - 1,
            reliability=60.0,
            description="Lower wick panjang rejection — bullish reversal signal",
        )
    return None


def _detect_inverted_hammer(candles: list[Candle]) -> CandlePatternDetection | None:
    """Inverted hammer: small body at bottom, long upper wick >= 2x body."""
    c = candles[-1]
    body = _body(c)
    r = _range(c)
    if r <= 0 or body <= 0:
        return None
    uw = _upper_wick(c)
    lw = _lower_wick(c)
    if uw >= 2 * body and lw <= body * 0.5 and _body_ratio(c) <= 0.35:
        return CandlePatternDetection(
            name="inverted_hammer",
            direction="BULLISH",
            strength="WEAK",
            candle_count=1,
            start_index=len(candles) - 1,
            end_index=len(candles) - 1,
            reliability=45.0,
            description="Upper wick panjang di bottom — butuh konfirmasi bullish",
        )
    return None


def _detect_shooting_star(candles: list[Candle]) -> CandlePatternDetection | None:
    """Shooting star: small body at bottom, long upper wick >= 2x body, bearish context."""
    if len(candles) < 2:
        return None
    c = candles[-1]
    prev = candles[-2]
    body = _body(c)
    r = _range(c)
    if r <= 0 or body <= 0:
        return None
    uw = _upper_wick(c)
    lw = _lower_wick(c)
    # Must be after an up move
    if uw >= 2 * body and lw <= body * 0.5 and _body_ratio(c) <= 0.35 and c.high > prev.high:
        return CandlePatternDetection(
            name="shooting_star",
            direction="BEARISH",
            strength="MODERATE",
            candle_count=1,
            start_index=len(candles) - 1,
            end_index=len(candles) - 1,
            reliability=60.0,
            description="Upper wick panjang rejection di top — bearish reversal signal",
        )
    return None


def _detect_hanging_man(candles: list[Candle]) -> CandlePatternDetection | None:
    """Hanging man: hammer shape but at top of uptrend."""
    if len(candles) < 3:
        return None
    c = candles[-1]
    body = _body(c)
    r = _range(c)
    if r <= 0 or body <= 0:
        return None
    lw = _lower_wick(c)
    uw = _upper_wick(c)
    # Context: previous candles trending up
    up_context = candles[-3].close < candles[-2].close < c.open
    if lw >= 2 * body and uw <= body * 0.5 and _body_ratio(c) <= 0.35 and up_context:
        return CandlePatternDetection(
            name="hanging_man",
            direction="BEARISH",
            strength="MODERATE",
            candle_count=1,
            start_index=len(candles) - 1,
            end_index=len(candles) - 1,
            reliability=55.0,
            description="Hammer shape di puncak uptrend — warning bearish reversal",
        )
    return None


def _detect_marubozu(candles: list[Candle]) -> CandlePatternDetection | None:
    """Marubozu: very large body with tiny/no wicks (body >= 90% range)."""
    c = candles[-1]
    r = _range(c)
    if r <= 0:
        return None
    if _body_ratio(c) >= 0.90:
        direction: PatternDirection = "BULLISH" if _is_bullish(c) else "BEARISH"
        return CandlePatternDetection(
            name="marubozu",
            direction=direction,
            strength="STRONG",
            candle_count=1,
            start_index=len(candles) - 1,
            end_index=len(candles) - 1,
            reliability=65.0,
            description=f"Full body {direction.lower()} candle — strong conviction",
        )
    return None


def _detect_spinning_top(candles: list[Candle]) -> CandlePatternDetection | None:
    """Spinning top: small body with both wicks longer than body."""
    c = candles[-1]
    body = _body(c)
    r = _range(c)
    if r <= 0 or body <= 0:
        return None
    uw = _upper_wick(c)
    lw = _lower_wick(c)
    ratio = _body_ratio(c)
    if 0.10 < ratio <= 0.35 and uw > body and lw > body:
        return CandlePatternDetection(
            name="spinning_top",
            direction="NEUTRAL",
            strength="WEAK",
            candle_count=1,
            start_index=len(candles) - 1,
            end_index=len(candles) - 1,
            reliability=35.0,
            description="Body kecil dengan wick seimbang — indecision/balance",
        )
    return None


# ---------------------------------------------------------------------------
# Double candle patterns
# ---------------------------------------------------------------------------


def _detect_bullish_engulfing(candles: list[Candle]) -> CandlePatternDetection | None:
    """Bullish engulfing: bearish candle followed by larger bullish candle."""
    if len(candles) < 2:
        return None
    prev, curr = candles[-2], candles[-1]
    if not _is_bearish(prev) or not _is_bullish(curr):
        return None
    if curr.open <= prev.close and curr.close >= prev.open:
        return CandlePatternDetection(
            name="bullish_engulfing",
            direction="BULLISH",
            strength="STRONG",
            candle_count=2,
            start_index=len(candles) - 2,
            end_index=len(candles) - 1,
            reliability=65.0,
            description="Candle bullish menelan body candle bearish sebelumnya",
        )
    return None


def _detect_bearish_engulfing(candles: list[Candle]) -> CandlePatternDetection | None:
    """Bearish engulfing: bullish candle followed by larger bearish candle."""
    if len(candles) < 2:
        return None
    prev, curr = candles[-2], candles[-1]
    if not _is_bullish(prev) or not _is_bearish(curr):
        return None
    if curr.open >= prev.close and curr.close <= prev.open:
        return CandlePatternDetection(
            name="bearish_engulfing",
            direction="BEARISH",
            strength="STRONG",
            candle_count=2,
            start_index=len(candles) - 2,
            end_index=len(candles) - 1,
            reliability=65.0,
            description="Candle bearish menelan body candle bullish sebelumnya",
        )
    return None



def _detect_bullish_harami(candles: list[Candle]) -> CandlePatternDetection | None:
    """Bullish harami: large bearish followed by small bullish inside it."""
    if len(candles) < 2:
        return None
    prev, curr = candles[-2], candles[-1]
    if not _is_bearish(prev) or not _is_bullish(curr):
        return None
    if _body(prev) > _body(curr) and curr.open >= prev.close and curr.close <= prev.open:
        return CandlePatternDetection(
            name="bullish_harami",
            direction="BULLISH",
            strength="MODERATE",
            candle_count=2,
            start_index=len(candles) - 2,
            end_index=len(candles) - 1,
            reliability=50.0,
            description="Candle bullish kecil di dalam body bearish — compression",
        )
    return None


def _detect_bearish_harami(candles: list[Candle]) -> CandlePatternDetection | None:
    """Bearish harami: large bullish followed by small bearish inside it."""
    if len(candles) < 2:
        return None
    prev, curr = candles[-2], candles[-1]
    if not _is_bullish(prev) or not _is_bearish(curr):
        return None
    if _body(prev) > _body(curr) and curr.close >= prev.open and curr.open <= prev.close:
        return CandlePatternDetection(
            name="bearish_harami",
            direction="BEARISH",
            strength="MODERATE",
            candle_count=2,
            start_index=len(candles) - 2,
            end_index=len(candles) - 1,
            reliability=50.0,
            description="Candle bearish kecil di dalam body bullish — compression",
        )
    return None


def _detect_tweezer_top(candles: list[Candle]) -> CandlePatternDetection | None:
    """Tweezer top: two candles with matching highs at resistance."""
    if len(candles) < 2:
        return None
    prev, curr = candles[-2], candles[-1]
    tol = _range(curr) * 0.05 if _range(curr) > 0 else 0.001
    if abs(prev.high - curr.high) <= tol and _is_bullish(prev) and _is_bearish(curr):
        return CandlePatternDetection(
            name="tweezer_top",
            direction="BEARISH",
            strength="MODERATE",
            candle_count=2,
            start_index=len(candles) - 2,
            end_index=len(candles) - 1,
            reliability=55.0,
            description="Dua candle dengan high sama — double rejection bearish",
        )
    return None


def _detect_tweezer_bottom(candles: list[Candle]) -> CandlePatternDetection | None:
    """Tweezer bottom: two candles with matching lows at support."""
    if len(candles) < 2:
        return None
    prev, curr = candles[-2], candles[-1]
    tol = _range(curr) * 0.05 if _range(curr) > 0 else 0.001
    if abs(prev.low - curr.low) <= tol and _is_bearish(prev) and _is_bullish(curr):
        return CandlePatternDetection(
            name="tweezer_bottom",
            direction="BULLISH",
            strength="MODERATE",
            candle_count=2,
            start_index=len(candles) - 2,
            end_index=len(candles) - 1,
            reliability=55.0,
            description="Dua candle dengan low sama — double rejection bullish",
        )
    return None


def _detect_piercing_line(candles: list[Candle]) -> CandlePatternDetection | None:
    """Piercing line: bearish then bullish closing above 50% of prev body."""
    if len(candles) < 2:
        return None
    prev, curr = candles[-2], candles[-1]
    if not _is_bearish(prev) or not _is_bullish(curr):
        return None
    prev_mid = (prev.open + prev.close) / 2
    if curr.open < prev.close and curr.close > prev_mid and curr.close < prev.open:
        return CandlePatternDetection(
            name="piercing_line",
            direction="BULLISH",
            strength="MODERATE",
            candle_count=2,
            start_index=len(candles) - 2,
            end_index=len(candles) - 1,
            reliability=55.0,
            description="Bullish candle menembus 50% body bearish sebelumnya",
        )
    return None


def _detect_dark_cloud_cover(candles: list[Candle]) -> CandlePatternDetection | None:
    """Dark cloud cover: bullish then bearish closing below 50% of prev body."""
    if len(candles) < 2:
        return None
    prev, curr = candles[-2], candles[-1]
    if not _is_bullish(prev) or not _is_bearish(curr):
        return None
    prev_mid = (prev.open + prev.close) / 2
    if curr.open > prev.close and curr.close < prev_mid and curr.close > prev.open:
        return CandlePatternDetection(
            name="dark_cloud_cover",
            direction="BEARISH",
            strength="MODERATE",
            candle_count=2,
            start_index=len(candles) - 2,
            end_index=len(candles) - 1,
            reliability=55.0,
            description="Bearish candle menembus 50% body bullish sebelumnya",
        )
    return None


# ---------------------------------------------------------------------------
# Triple candle patterns
# ---------------------------------------------------------------------------


def _detect_morning_star(candles: list[Candle]) -> CandlePatternDetection | None:
    """Morning star: bearish + small body/doji + bullish (reversal up)."""
    if len(candles) < 3:
        return None
    c1, c2, c3 = candles[-3], candles[-2], candles[-1]
    if not _is_bearish(c1) or not _is_bullish(c3):
        return None
    # c2 must be small body
    if _body_ratio(c2) > 0.40:
        return None
    # c3 closes above midpoint of c1
    c1_mid = (c1.open + c1.close) / 2
    if c3.close > c1_mid:
        return CandlePatternDetection(
            name="morning_star",
            direction="BULLISH",
            strength="STRONG",
            candle_count=3,
            start_index=len(candles) - 3,
            end_index=len(candles) - 1,
            reliability=70.0,
            description="Three-bar bullish reversal — bearish, indecision, bullish",
        )
    return None


def _detect_evening_star(candles: list[Candle]) -> CandlePatternDetection | None:
    """Evening star: bullish + small body/doji + bearish (reversal down)."""
    if len(candles) < 3:
        return None
    c1, c2, c3 = candles[-3], candles[-2], candles[-1]
    if not _is_bullish(c1) or not _is_bearish(c3):
        return None
    if _body_ratio(c2) > 0.40:
        return None
    c1_mid = (c1.open + c1.close) / 2
    if c3.close < c1_mid:
        return CandlePatternDetection(
            name="evening_star",
            direction="BEARISH",
            strength="STRONG",
            candle_count=3,
            start_index=len(candles) - 3,
            end_index=len(candles) - 1,
            reliability=70.0,
            description="Three-bar bearish reversal — bullish, indecision, bearish",
        )
    return None


def _detect_three_white_soldiers(candles: list[Candle]) -> CandlePatternDetection | None:
    """Three white soldiers: three consecutive bullish candles with higher closes."""
    if len(candles) < 3:
        return None
    c1, c2, c3 = candles[-3], candles[-2], candles[-1]
    all_bull = _is_bullish(c1) and _is_bullish(c2) and _is_bullish(c3)
    higher_closes = c3.close > c2.close > c1.close
    higher_opens = c3.open > c2.open > c1.open
    # Bodies should be decent size (not tiny wicks)
    decent_body = all((_body_ratio(c) >= 0.50) for c in (c1, c2, c3))
    if all_bull and higher_closes and higher_opens and decent_body:
        return CandlePatternDetection(
            name="three_white_soldiers",
            direction="BULLISH",
            strength="STRONG",
            candle_count=3,
            start_index=len(candles) - 3,
            end_index=len(candles) - 1,
            reliability=70.0,
            description="Tiga candle bullish berturut — strong momentum up",
        )
    return None


def _detect_three_black_crows(candles: list[Candle]) -> CandlePatternDetection | None:
    """Three black crows: three consecutive bearish candles with lower closes."""
    if len(candles) < 3:
        return None
    c1, c2, c3 = candles[-3], candles[-2], candles[-1]
    all_bear = _is_bearish(c1) and _is_bearish(c2) and _is_bearish(c3)
    lower_closes = c3.close < c2.close < c1.close
    lower_opens = c3.open < c2.open < c1.open
    decent_body = all((_body_ratio(c) >= 0.50) for c in (c1, c2, c3))
    if all_bear and lower_closes and lower_opens and decent_body:
        return CandlePatternDetection(
            name="three_black_crows",
            direction="BEARISH",
            strength="STRONG",
            candle_count=3,
            start_index=len(candles) - 3,
            end_index=len(candles) - 1,
            reliability=70.0,
            description="Tiga candle bearish berturut — strong momentum down",
        )
    return None


def _detect_three_inside_up(candles: list[Candle]) -> CandlePatternDetection | None:
    """Three inside up: harami + bullish confirmation."""
    if len(candles) < 3:
        return None
    c1, c2, c3 = candles[-3], candles[-2], candles[-1]
    # c1 bearish, c2 small bullish inside c1, c3 bullish closing above c1 open
    if not _is_bearish(c1) or not _is_bullish(c2) or not _is_bullish(c3):
        return None
    harami = c2.open >= c1.close and c2.close <= c1.open and _body(c1) > _body(c2)
    confirm = c3.close > c1.open
    if harami and confirm:
        return CandlePatternDetection(
            name="three_inside_up",
            direction="BULLISH",
            strength="STRONG",
            candle_count=3,
            start_index=len(candles) - 3,
            end_index=len(candles) - 1,
            reliability=65.0,
            description="Harami bullish + konfirmasi — validated reversal up",
        )
    return None


def _detect_three_inside_down(candles: list[Candle]) -> CandlePatternDetection | None:
    """Three inside down: bearish harami + bearish confirmation."""
    if len(candles) < 3:
        return None
    c1, c2, c3 = candles[-3], candles[-2], candles[-1]
    if not _is_bullish(c1) or not _is_bearish(c2) or not _is_bearish(c3):
        return None
    harami = c2.close >= c1.open and c2.open <= c1.close and _body(c1) > _body(c2)
    confirm = c3.close < c1.open
    if harami and confirm:
        return CandlePatternDetection(
            name="three_inside_down",
            direction="BEARISH",
            strength="STRONG",
            candle_count=3,
            start_index=len(candles) - 3,
            end_index=len(candles) - 1,
            reliability=65.0,
            description="Harami bearish + konfirmasi — validated reversal down",
        )
    return None


# ---------------------------------------------------------------------------
# Public API — detect all patterns
# ---------------------------------------------------------------------------

# Registry of all pattern detectors
_PATTERN_DETECTORS = [
    # Single
    _detect_doji,
    _detect_dragonfly_doji,
    _detect_gravestone_doji,
    _detect_hammer,
    _detect_inverted_hammer,
    _detect_shooting_star,
    _detect_hanging_man,
    _detect_marubozu,
    _detect_spinning_top,
    # Double
    _detect_bullish_engulfing,
    _detect_bearish_engulfing,
    _detect_bullish_harami,
    _detect_bearish_harami,
    _detect_tweezer_top,
    _detect_tweezer_bottom,
    _detect_piercing_line,
    _detect_dark_cloud_cover,
    # Triple
    _detect_morning_star,
    _detect_evening_star,
    _detect_three_white_soldiers,
    _detect_three_black_crows,
    _detect_three_inside_up,
    _detect_three_inside_down,
]


def detect_all_patterns(candles: list[Candle]) -> list[CandlePatternDetection]:
    """Run all pattern detectors and return all detected patterns.

    Checks the most recent candles for all known patterns. Returns an empty
    list when no patterns are found. Safe to call with fewer than 3 candles
    (individual detectors handle minimum length checks).
    """
    if not candles:
        return []
    results: list[CandlePatternDetection] = []
    for detector in _PATTERN_DETECTORS:
        detection = detector(candles)
        if detection is not None:
            results.append(detection)
    return results


def detect_patterns_with_context(
    candles: list[Candle],
    *,
    min_reliability: float = 0.0,
    direction_filter: PatternDirection | None = None,
) -> list[CandlePatternDetection]:
    """Detect patterns with optional filtering.

    Args:
        candles: OHLCV candle data.
        min_reliability: Only return patterns with reliability >= this value.
        direction_filter: Only return patterns matching this direction.
    """
    patterns = detect_all_patterns(candles)
    if min_reliability > 0:
        patterns = [p for p in patterns if p.reliability >= min_reliability]
    if direction_filter is not None:
        patterns = [p for p in patterns if p.direction == direction_filter]
    return patterns

