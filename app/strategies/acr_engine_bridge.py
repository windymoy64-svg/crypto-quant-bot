"""Bridge antara ACR+ position manager dan ``RealtimePaperTradingEngine``.

Helper opsional untuk meng-upgrade trailing stop, break-even, dan invalidation
di ``app/paper/realtime_engine.py`` dari ATR-based menjadi **swing-based
(ACR+)**, tanpa mengubah struktur position dict.

Semua fungsi bersifat "apply-if-eligible": bila candle tidak cukup atau state
belum lengkap, mereka return no-op. Ini menjaga backward-compatibility.

Format position dict yang diharapkan:
    {
        "side": "BUY" | "SELL",
        "entry": float,
        "static_stop_loss": float,
        "trailing_stop_loss": float | None,
        "trailing_active": bool,
        "tp_hit": [bool, bool, bool],
        "take_profit": [float, float, float],
        ...
    }
"""

from __future__ import annotations

from typing import Any

from app.core.models import Candle
from app.indicators.acr import (
    Direction,
    acr_swings,
    cisd_levels,
    latest_acr_pattern,
)


DEFAULT_TRAIL_BUFFER_PCT: float = 0.002    # 0.2%


def _side_direction(position: dict[str, Any]) -> Direction | None:
    side = str(position.get("side", "")).upper()
    if side in ("BUY", "LONG"):
        return "BULLISH"
    if side in ("SELL", "SHORT"):
        return "BEARISH"
    return None


def _is_long(position: dict[str, Any]) -> bool:
    return _side_direction(position) == "BULLISH"



# ---------------------------------------------------------------------------
# Break-even
# ---------------------------------------------------------------------------


def apply_acr_breakeven(position: dict[str, Any]) -> bool:
    """Geser ``static_stop_loss`` ke entry setelah TP1 hit.

    Aturan ACR+ Notes: setelah TP1 (fix 2R), SL wajib ke break-even.
    Return ``True`` bila SL berubah.
    """

    tp_hit = position.get("tp_hit") or [False, False, False]
    if not isinstance(tp_hit, list) or len(tp_hit) < 1 or not tp_hit[0]:
        return False

    entry = float(position.get("entry", 0.0))
    current_static = float(position.get("static_stop_loss", entry))

    if _is_long(position):
        if current_static < entry:
            position["static_stop_loss"] = entry
            return True
        return False
    # SHORT
    if current_static > entry:
        position["static_stop_loss"] = entry
        return True
    return False


# ---------------------------------------------------------------------------
# Trailing stop swing-based
# ---------------------------------------------------------------------------


def _compute_swing_trailing(
    position: dict[str, Any],
    ltf_candles: list[Candle],
    buffer_pct: float,
) -> float | None:
    """Hitung level trailing berdasarkan swing terakhir searah bias posisi."""

    if not ltf_candles or len(ltf_candles) < 3:
        return None

    swings = acr_swings(ltf_candles)
    current_price = float(ltf_candles[-1].close)

    if _is_long(position):
        lows = [s for s in swings if s.side == "LOW"]
        if not lows:
            return None
        candidate = lows[-1].price * (1 - buffer_pct)
        current_trail = position.get("trailing_stop_loss")
        current_trail_val = (
            float(current_trail) if current_trail is not None else float("-inf")
        )
        if candidate <= current_trail_val or candidate >= current_price:
            return None
        return candidate
    # SHORT
    highs = [s for s in swings if s.side == "HIGH"]
    if not highs:
        return None
    candidate = highs[-1].price * (1 + buffer_pct)
    current_trail = position.get("trailing_stop_loss")
    current_trail_val = (
        float(current_trail) if current_trail is not None else float("inf")
    )
    if candidate >= current_trail_val or candidate <= current_price:
        return None
    return candidate


def apply_acr_trailing(
    position: dict[str, Any],
    ltf_candles: list[Candle],
    *,
    buffer_pct: float = DEFAULT_TRAIL_BUFFER_PCT,
    require_tp1_hit: bool = True,
) -> bool:
    """Update ``trailing_stop_loss`` berdasarkan swing terakhir.

    - ``require_tp1_hit`` (default True): trailing hanya aktif setelah TP1 hit.
    - Return ``True`` bila SL trailing berubah.
    """

    if require_tp1_hit:
        tp_hit = position.get("tp_hit") or [False, False, False]
        if not (isinstance(tp_hit, list) and tp_hit and tp_hit[0]):
            return False

    trailing = _compute_swing_trailing(position, ltf_candles, buffer_pct)
    if trailing is None:
        return False

    position["trailing_stop_loss"] = trailing
    position["trailing_active"] = True
    return True


# ---------------------------------------------------------------------------
# Invalidation
# ---------------------------------------------------------------------------


def check_acr_invalidation(
    position: dict[str, Any],
    ltf_candles: list[Candle],
    *,
    require_tp1_hit: bool = True,
) -> str | None:
    """Cek apakah muncul CISD atau ACR pattern lawan arah setelah entry.

    Return alasan invalidation (string) atau ``None``.

    - ``require_tp1_hit``: kalau True, hanya cek setelah TP1 sudah kena
      (menghindari premature exit).
    """

    direction = _side_direction(position)
    if direction is None:
        return None

    if require_tp1_hit:
        tp_hit = position.get("tp_hit") or [False, False, False]
        if not (isinstance(tp_hit, list) and tp_hit and tp_hit[0]):
            return None

    opposite: Direction = "BEARISH" if direction == "BULLISH" else "BULLISH"

    counter_cisds = [c for c in cisd_levels(ltf_candles) if c.direction == opposite]
    if counter_cisds:
        return "counter_cisd"

    counter_pattern = latest_acr_pattern(
        ltf_candles, direction=opposite, require_actionable=True
    )
    if counter_pattern is not None:
        return "counter_acr_pattern"

    return None


__all__ = [
    "DEFAULT_TRAIL_BUFFER_PCT",
    "apply_acr_breakeven",
    "apply_acr_trailing",
    "check_acr_invalidation",
]

