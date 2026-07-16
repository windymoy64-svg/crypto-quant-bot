"""Auden Candle Range (ACR+) primitives.

Deterministic detectors untuk methodologi ACR+ dari AudenFX Mentorship:

- **Swing Point 3-candle**: candle tengah membentuk high/low relatif terhadap
  candle kiri dan kanan.
- **FVG (Fair Value Gap)**: formasi 3 candle dengan gap antara high candle 1
  dan low candle 3 (bullish) atau kebalikannya (bearish). Warna candle tidak
  berpengaruh.
- **CISD (Change In State of Delivery)**: body candle menembus close candle
  beda warna pertama sebelumnya (bukan wick).
- **MSS (Market Structure Shift)**: break swing berdasarkan wick.
- **Opposing Candle**: open candle pertama dari rangkaian candle lawan arah,
  jadi key level entry / SL.
- **ACR Pattern (Candle 1-2-3-4)**: formasi 4-candle klasik dengan aturan
  respect equilibrium wick candle 2.
- **Premium & Discount / Equilibrium**: 50% dari range swing.
- **Equilibrium Previous Candle**: reversal (dari wick candle sebelumnya) dan
  continuation (dari full high-low candle sebelumnya).

Modul ini pure, deterministic, tanpa I/O. Fungsi tidak mengubah input.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

from app.core.models import Candle


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


Direction = Literal["BULLISH", "BEARISH"]
Side = Literal["HIGH", "LOW"]


@dataclass(frozen=True)
class ACRSwing:
    """Swing point berbasis formasi 3 candle."""

    index: int
    side: Side
    price: float
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FairValueGap:
    """Fair Value Gap tiga-candle."""

    direction: Direction
    top: float
    bottom: float
    left_index: int
    middle_index: int
    right_index: int
    timestamp: str
    mitigated: bool = False
    filled: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def size(self) -> float:
        return self.top - self.bottom

    @property
    def midpoint(self) -> float:
        return (self.top + self.bottom) / 2

    def contains(self, price: float) -> bool:
        return self.bottom <= price <= self.top


@dataclass(frozen=True)
class CISDLevel:
    """Change In State of Delivery (body break)."""

    direction: Direction
    price: float
    broken_index: int
    break_index: int
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MSSEvent:
    """Market Structure Shift (wick break of a swing)."""

    direction: Direction
    swing_price: float
    swing_index: int
    break_index: int
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OpposingCandle:
    """Open candle pertama dari rangkaian candle lawan arah."""

    direction: Direction  # arah setelah reversal yang diharapkan
    price: float
    index: int
    series_length: int
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ACRPattern:
    """ACR Formation Candle 1-2-3-4."""

    direction: Direction
    candle1_index: int
    candle2_index: int
    candle3_index: int | None
    candle4_index: int | None
    swing_price: float
    equilibrium: float
    candle2_wick_far: float
    stage: Literal["forming", "confirmed", "expanded", "invalid"]
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["reasons"] = list(self.reasons)
        return data

    @property
    def is_actionable(self) -> bool:
        return self.stage in ("confirmed", "expanded")


@dataclass(frozen=True)
class EquilibriumRange:
    """Range dan 50% (equilibrium) untuk premium/discount analysis."""

    direction: Direction
    swing_low: float
    swing_high: float
    equilibrium: float
    low_index: int
    high_index: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def discount_zone(self) -> tuple[float, float]:
        return (self.swing_low, self.equilibrium)

    @property
    def premium_zone(self) -> tuple[float, float]:
        return (self.equilibrium, self.swing_high)

    def is_discount(self, price: float) -> bool:
        return self.swing_low <= price <= self.equilibrium

    def is_premium(self, price: float) -> bool:
        return self.equilibrium <= price <= self.swing_high


# ---------------------------------------------------------------------------
# Basic candle helpers
# ---------------------------------------------------------------------------


def _is_bullish(candle: Candle) -> bool:
    return candle.close > candle.open


def _is_bearish(candle: Candle) -> bool:
    return candle.close < candle.open


def _body_top(candle: Candle) -> float:
    return max(candle.open, candle.close)


def _body_bottom(candle: Candle) -> float:
    return min(candle.open, candle.close)


# ---------------------------------------------------------------------------
# Swing detection (3-candle formation, per ACR spec)
# ---------------------------------------------------------------------------


def acr_swings(candles: list[Candle]) -> list[ACRSwing]:
    """Deteksi swing high & low formasi 3 candle (candle tengah paling extreme).

    Sesuai spec ACR: swing high = candle tengah punya high strictly lebih
    tinggi dari kiri & kanan. Warna dan ukuran candle tidak berpengaruh.
    """

    swings: list[ACRSwing] = []
    if len(candles) < 3:
        return swings
    for i in range(1, len(candles) - 1):
        left, mid, right = candles[i - 1], candles[i], candles[i + 1]
        if mid.high > left.high and mid.high > right.high:
            swings.append(
                ACRSwing(index=i, side="HIGH", price=mid.high, timestamp=mid.timestamp)
            )
        if mid.low < left.low and mid.low < right.low:
            swings.append(
                ACRSwing(index=i, side="LOW", price=mid.low, timestamp=mid.timestamp)
            )
    return swings


# ---------------------------------------------------------------------------
# Fair Value Gap
# ---------------------------------------------------------------------------


def fair_value_gaps(candles: list[Candle]) -> list[FairValueGap]:
    """Deteksi semua FVG bullish/bearish dari formasi 3-candle.

    Bullish FVG: ``candles[i+2].low > candles[i].high``.
    Bearish FVG: ``candles[i+2].high < candles[i].low``.
    ``mitigated``: wick candle setelah candle3 menyentuh gap.
    ``filled``: wick candle setelah candle3 menembus penuh sisi lawan.
    """

    fvgs: list[FairValueGap] = []
    for i in range(len(candles) - 2):
        c1, c2, c3 = candles[i], candles[i + 1], candles[i + 2]
        if c3.low > c1.high:
            top = c3.low
            bottom = c1.high
            mitigated = False
            filled = False
            for later in candles[i + 3 :]:
                if later.low <= top:
                    mitigated = True
                    if later.low <= bottom:
                        filled = True
                        break
            fvgs.append(
                FairValueGap(
                    direction="BULLISH",
                    top=top,
                    bottom=bottom,
                    left_index=i,
                    middle_index=i + 1,
                    right_index=i + 2,
                    timestamp=c2.timestamp,
                    mitigated=mitigated,
                    filled=filled,
                )
            )
        if c3.high < c1.low:
            top = c1.low
            bottom = c3.high
            mitigated = False
            filled = False
            for later in candles[i + 3 :]:
                if later.high >= bottom:
                    mitigated = True
                    if later.high >= top:
                        filled = True
                        break
            fvgs.append(
                FairValueGap(
                    direction="BEARISH",
                    top=top,
                    bottom=bottom,
                    left_index=i,
                    middle_index=i + 1,
                    right_index=i + 2,
                    timestamp=c2.timestamp,
                    mitigated=mitigated,
                    filled=filled,
                )
            )
    return fvgs


def latest_unfilled_fvg(
    fvgs: list[FairValueGap], direction: Direction
) -> FairValueGap | None:
    """FVG terbaru searah yang belum fully filled."""

    candidates = [f for f in fvgs if f.direction == direction and not f.filled]
    return candidates[-1] if candidates else None



# ---------------------------------------------------------------------------
# CISD (body break) & MSS (wick break)
# ---------------------------------------------------------------------------


def cisd_levels(candles: list[Candle]) -> list[CISDLevel]:
    """Deteksi semua CISD (body break candle beda warna pertama).

    Algoritma:
      1. Untuk tiap candle ``i``, jika berwarna beda dari ``i-1``, catat
         sebagai kandidat "candle beda warna pertama".
      2. CISD terjadi ketika body candle ``j > i`` menutup melewati close
         candle ``i``:
         - Bullish CISD: candle i bearish, candle j bullish, close j >
           close i. Level = close candle i (body bawah).
         - Bearish CISD: candle i bullish, candle j bearish, close j <
           close i. Level = close candle i (body atas).
      3. Ambil break pertama per kandidat, catat sekali.

    Beda dari MSS: CISD selalu **body break** (close), MSS memakai wick
    break (high/low).
    """

    levels: list[CISDLevel] = []
    for i in range(1, len(candles)):
        current = candles[i]
        prev = candles[i - 1]

        # Bullish candle di dalam rangkaian bearish -> pantau bearish CISD
        if _is_bullish(current) and _is_bearish(prev):
            level_price = current.close  # body atas
            for j in range(i + 1, len(candles)):
                cj = candles[j]
                if _is_bearish(cj) and cj.close < level_price:
                    levels.append(
                        CISDLevel(
                            direction="BEARISH",
                            price=level_price,
                            broken_index=i,
                            break_index=j,
                            timestamp=cj.timestamp,
                        )
                    )
                    break

        # Bearish candle di dalam rangkaian bullish -> pantau bullish CISD
        if _is_bearish(current) and _is_bullish(prev):
            level_price = current.close  # body bawah
            for j in range(i + 1, len(candles)):
                cj = candles[j]
                if _is_bullish(cj) and cj.close > level_price:
                    levels.append(
                        CISDLevel(
                            direction="BULLISH",
                            price=level_price,
                            broken_index=i,
                            break_index=j,
                            timestamp=cj.timestamp,
                        )
                    )
                    break
    return levels


def latest_cisd(cisds: list[CISDLevel], direction: Direction) -> CISDLevel | None:
    """CISD terbaru untuk arah tertentu."""

    candidates = [c for c in cisds if c.direction == direction]
    return candidates[-1] if candidates else None


def mss_events(
    candles: list[Candle], swings: list[ACRSwing] | None = None
) -> list[MSSEvent]:
    """Deteksi Market Structure Shift (break swing berbasis wick).

    Bullish MSS: swing HIGH dilewati wick candle setelahnya (high >= swing).
    Bearish MSS: swing LOW dilewati wick candle setelahnya (low <= swing).
    """

    swings_local = swings if swings is not None else acr_swings(candles)
    events: list[MSSEvent] = []
    for swing in swings_local:
        target_dir: Direction = "BULLISH" if swing.side == "HIGH" else "BEARISH"
        for j in range(swing.index + 1, len(candles)):
            cj = candles[j]
            if swing.side == "HIGH" and cj.high >= swing.price:
                events.append(
                    MSSEvent(
                        direction=target_dir,
                        swing_price=swing.price,
                        swing_index=swing.index,
                        break_index=j,
                        timestamp=cj.timestamp,
                    )
                )
                break
            if swing.side == "LOW" and cj.low <= swing.price:
                events.append(
                    MSSEvent(
                        direction=target_dir,
                        swing_price=swing.price,
                        swing_index=swing.index,
                        break_index=j,
                        timestamp=cj.timestamp,
                    )
                )
                break
    return events




# ---------------------------------------------------------------------------
# Opposing Candle
# ---------------------------------------------------------------------------


def opposing_candles(candles: list[Candle]) -> list[OpposingCandle]:
    """Deteksi opposing candle level dari rangkaian candle sewarna.

    Aturan ACR:
      - Rangkaian downclose (candle bearish berturut-turut): pivot = candle
        downclose paling *tinggi* (open) di seri. Ini menjadi resistance /
        entry SELL berikutnya. ``direction`` = BEARISH.
      - Rangkaian upclose (candle bullish berturut-turut): pivot = candle
        upclose paling *rendah* (open) di seri. Ini menjadi support / entry
        BUY berikutnya. ``direction`` = BULLISH.

    Doji dianggap netral: tidak memutus seri, tetapi juga tidak menambah
    panjangnya.
    """

    levels: list[OpposingCandle] = []
    if not candles:
        return levels

    def _dir(c: Candle) -> Direction | None:
        if _is_bullish(c):
            return "BULLISH"
        if _is_bearish(c):
            return "BEARISH"
        return None

    start = 0
    current_dir: Direction | None = _dir(candles[0])

    for i in range(1, len(candles) + 1):
        boundary = i == len(candles)
        new_dir = None if boundary else _dir(candles[i])
        # Doji dilewati (tidak ganti seri) selama belum di batas.
        if not boundary and new_dir is None:
            continue
        if new_dir != current_dir and current_dir is not None:
            series = candles[start:i]
            if series:
                if current_dir == "BULLISH":
                    # Rangkaian upclose -> opposing untuk arah bearish (resistance).
                    # Spec ACR: open candle upclose PALING RENDAH di seri.
                    pivot = min(series, key=lambda c: c.open)
                    pivot_idx = start + series.index(pivot)
                    levels.append(
                        OpposingCandle(
                            direction="BEARISH",
                            price=pivot.open,
                            index=pivot_idx,
                            series_length=len(series),
                            timestamp=pivot.timestamp,
                        )
                    )
                else:  # BEARISH series (rangkaian downclose)
                    # Spec ACR: open candle downclose PALING TINGGI di seri.
                    pivot = max(series, key=lambda c: c.open)
                    pivot_idx = start + series.index(pivot)
                    levels.append(
                        OpposingCandle(
                            direction="BULLISH",
                            price=pivot.open,
                            index=pivot_idx,
                            series_length=len(series),
                            timestamp=pivot.timestamp,
                        )
                    )
            start = i
            current_dir = new_dir
        elif new_dir == current_dir and current_dir is None and not boundary:
            start = i  # gulir cursor melewati doji awal

    return levels


def latest_opposing(
    opps: list[OpposingCandle],
    direction: Direction,
    reference_index: int | None = None,
) -> OpposingCandle | None:
    """Opposing candle terbaru untuk arah tertentu.

    Bila ``reference_index`` diberikan, hanya kandidat dengan
    ``index <= reference_index`` yang dipertimbangkan.
    """

    candidates = [o for o in opps if o.direction == direction]
    if reference_index is not None:
        candidates = [o for o in candidates if o.index <= reference_index]
    return candidates[-1] if candidates else None




# ---------------------------------------------------------------------------
# ACR Pattern (Candle 1-2-3-4)
# ---------------------------------------------------------------------------


def _wick_equilibrium(candle: Candle, side: Side) -> float:
    """50% dari wick candle sesuai spec ACR ("2 Candle Close: Wick").

    - Untuk swing LOW (bullish reversal): wick bawah antara ``low`` ke
      ``body_bottom``. Jika wick lumayan (>=15% full range), equilibrium
      = midpoint wick bawah. Jika tidak, fallback ke midpoint full candle
      (spec "2 Candle Close: Tanpa Wick").
    - Untuk swing HIGH (bearish reversal): mirror pada wick atas.
    """

    body_top = _body_top(candle)
    body_bottom = _body_bottom(candle)
    full_range = candle.high - candle.low
    if full_range <= 0:
        return candle.close
    if side == "HIGH":
        upper_wick = candle.high - body_top
        if upper_wick / full_range >= 0.15:
            return body_top + upper_wick / 2
        return (candle.high + candle.low) / 2
    lower_wick = body_bottom - candle.low
    if lower_wick / full_range >= 0.15:
        return candle.low + lower_wick / 2
    return (candle.high + candle.low) / 2


def _build_pattern(
    *,
    direction: Direction,
    candle1_index: int,
    candle2_index: int,
    candle3_index: int | None,
    candle4_index: int | None,
    swing_price: float,
    equilibrium: float,
    candle2_wick_far: float,
    stage: str,
    reasons: list[str],
) -> ACRPattern:
    return ACRPattern(
        direction=direction,
        candle1_index=candle1_index,
        candle2_index=candle2_index,
        candle3_index=candle3_index,
        candle4_index=candle4_index,
        swing_price=swing_price,
        equilibrium=equilibrium,
        candle2_wick_far=candle2_wick_far,
        stage=stage,  # type: ignore[arg-type]
        reasons=list(reasons),
    )


def detect_acr_pattern_at(
    candles: list[Candle], candle2_index: int
) -> ACRPattern | None:
    """Cek apakah candle di ``candle2_index`` membentuk ACR valid.

    Aturan Bullish ACR:
      - Candle 2 low < Candle 1 low (sweep low candle 1)
      - Candle 2 close >= Candle 1 low (close balik ke range candle 1)
      - Candle 3 close > equilibrium wick candle 2 (respect equilibrium)
      - Candle 4 lanjut naik (close > close candle 3) -> ``expanded``

    Bearish ACR: mirror.

    Return ``None`` bila candle 2 tidak memenuhi swing sweep.
    """

    if candle2_index < 1 or candle2_index >= len(candles):
        return None

    c1 = candles[candle2_index - 1]
    c2 = candles[candle2_index]

    # --- Bullish detection ---
    if c2.low < c1.low and c2.close >= c1.low:
        equilibrium = _wick_equilibrium(c2, "LOW")
        reasons = [
            "candle2_swept_candle1_low",
            "candle2_closed_back_in_range",
        ]
        common = {
            "direction": "BULLISH",
            "candle1_index": candle2_index - 1,
            "candle2_index": candle2_index,
            "swing_price": c2.low,
            "equilibrium": equilibrium,
            "candle2_wick_far": c2.low,
        }

        c3_index = candle2_index + 1
        if c3_index >= len(candles):
            return _build_pattern(
                candle3_index=None, candle4_index=None,
                stage="forming", reasons=reasons, **common,
            )
        c3 = candles[c3_index]
        if c3.close <= equilibrium:
            reasons.append("candle3_failed_equilibrium")
            return _build_pattern(
                candle3_index=c3_index, candle4_index=None,
                stage="invalid", reasons=reasons, **common,
            )
        reasons.append("candle3_strong_close_above_equilibrium")

        c4_index = candle2_index + 2
        if c4_index >= len(candles):
            return _build_pattern(
                candle3_index=c3_index, candle4_index=None,
                stage="confirmed", reasons=reasons, **common,
            )
        c4 = candles[c4_index]
        if c4.close > c3.close:
            reasons.append("candle4_expansion_bullish")
            return _build_pattern(
                candle3_index=c3_index, candle4_index=c4_index,
                stage="expanded", reasons=reasons, **common,
            )
        return _build_pattern(
            candle3_index=c3_index, candle4_index=c4_index,
            stage="confirmed", reasons=reasons, **common,
        )

    # --- Bearish detection ---
    if c2.high > c1.high and c2.close <= c1.high:
        equilibrium = _wick_equilibrium(c2, "HIGH")
        reasons = [
            "candle2_swept_candle1_high",
            "candle2_closed_back_in_range",
        ]
        common = {
            "direction": "BEARISH",
            "candle1_index": candle2_index - 1,
            "candle2_index": candle2_index,
            "swing_price": c2.high,
            "equilibrium": equilibrium,
            "candle2_wick_far": c2.high,
        }

        c3_index = candle2_index + 1
        if c3_index >= len(candles):
            return _build_pattern(
                candle3_index=None, candle4_index=None,
                stage="forming", reasons=reasons, **common,
            )
        c3 = candles[c3_index]
        if c3.close >= equilibrium:
            reasons.append("candle3_failed_equilibrium")
            return _build_pattern(
                candle3_index=c3_index, candle4_index=None,
                stage="invalid", reasons=reasons, **common,
            )
        reasons.append("candle3_strong_close_below_equilibrium")

        c4_index = candle2_index + 2
        if c4_index >= len(candles):
            return _build_pattern(
                candle3_index=c3_index, candle4_index=None,
                stage="confirmed", reasons=reasons, **common,
            )
        c4 = candles[c4_index]
        if c4.close < c3.close:
            reasons.append("candle4_expansion_bearish")
            return _build_pattern(
                candle3_index=c3_index, candle4_index=c4_index,
                stage="expanded", reasons=reasons, **common,
            )
        return _build_pattern(
            candle3_index=c3_index, candle4_index=c4_index,
            stage="confirmed", reasons=reasons, **common,
        )

    return None




def latest_acr_pattern(
    candles: list[Candle],
    direction: Direction | None = None,
    require_actionable: bool = True,
) -> ACRPattern | None:
    """Scan candle terbaru untuk ACR pattern.

    - ``direction``: batasi hanya BULLISH atau BEARISH bila diberikan.
    - ``require_actionable``: hanya pattern ``confirmed`` atau ``expanded``.
      Pattern ``forming`` / ``invalid`` di-skip.
    """

    for i in range(len(candles) - 1, 0, -1):
        pattern = detect_acr_pattern_at(candles, i)
        if pattern is None:
            continue
        if direction is not None and pattern.direction != direction:
            continue
        if require_actionable and not pattern.is_actionable:
            continue
        return pattern
    return None


# ---------------------------------------------------------------------------
# Premium / Discount & Equilibrium Previous Candle
# ---------------------------------------------------------------------------


def equilibrium_range_from_swings(
    swing_low: ACRSwing, swing_high: ACRSwing
) -> EquilibriumRange:
    """Bangun equilibrium range dari sepasang swing.

    Arah otomatis: jika ``swing_low.index < swing_high.index`` -> BULLISH range
    (untuk mencari BUY di discount). Sebaliknya BEARISH.
    """

    direction: Direction = (
        "BULLISH" if swing_low.index < swing_high.index else "BEARISH"
    )
    equilibrium = (swing_low.price + swing_high.price) / 2
    return EquilibriumRange(
        direction=direction,
        swing_low=swing_low.price,
        swing_high=swing_high.price,
        equilibrium=equilibrium,
        low_index=swing_low.index,
        high_index=swing_high.index,
    )


def latest_equilibrium_range(candles: list[Candle]) -> EquilibriumRange | None:
    """Bangun equilibrium dari swing high & swing low terbaru."""

    swings = acr_swings(candles)
    if not swings:
        return None
    last_high = next((s for s in reversed(swings) if s.side == "HIGH"), None)
    last_low = next((s for s in reversed(swings) if s.side == "LOW"), None)
    if last_high is None or last_low is None:
        return None
    return equilibrium_range_from_swings(last_low, last_high)


def previous_candle_equilibrium_continuation(candle: Candle) -> float:
    """50% dari full high-low candle (kasus continuation)."""

    return (candle.high + candle.low) / 2


def previous_candle_equilibrium_reversal(candle: Candle, side: Side) -> float:
    """50% dari wick candle (kasus reversal).

    ``side`` = HIGH untuk bearish reversal (wick atas), LOW untuk bullish
    reversal (wick bawah).
    """

    return _wick_equilibrium(candle, side)


# ---------------------------------------------------------------------------
# Displacement helper
# ---------------------------------------------------------------------------


def has_displacement_fvg(
    candles: list[Candle],
    direction: Direction,
    after_index: int,
    lookforward: int = 5,
) -> FairValueGap | None:
    """Cek apakah muncul FVG searah setelah ``after_index`` (displacement).

    Return FVG paling baru dalam window ``lookforward`` candle setelah
    ``after_index``, atau ``None`` bila tidak ada.
    """

    end = min(len(candles), after_index + lookforward + 3)
    scoped = candles[:end]
    fvgs = fair_value_gaps(scoped)
    matching = [
        f
        for f in fvgs
        if f.direction == direction and f.left_index >= after_index
    ]
    return matching[-1] if matching else None


__all__ = [
    "ACRPattern",
    "ACRSwing",
    "CISDLevel",
    "Direction",
    "EquilibriumRange",
    "FairValueGap",
    "MSSEvent",
    "OpposingCandle",
    "Side",
    "acr_swings",
    "cisd_levels",
    "detect_acr_pattern_at",
    "equilibrium_range_from_swings",
    "fair_value_gaps",
    "has_displacement_fvg",
    "latest_acr_pattern",
    "latest_cisd",
    "latest_equilibrium_range",
    "latest_opposing",
    "latest_unfilled_fvg",
    "mss_events",
    "opposing_candles",
    "previous_candle_equilibrium_continuation",
    "previous_candle_equilibrium_reversal",
]

