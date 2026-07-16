"""ACR+ Position Manager.

State machine deterministic untuk mengelola posisi yang sudah aktif menurut
metodologi ACR+:

- **Break-even**: setelah TP1 tercapai, SL dinaikkan ke entry (long) atau
  diturunkan ke entry (short). Aturan "free ride" (ACR+ Notes: "TP fix 2R").
- **Trailing stop**: setelah TP2 tercapai, SL trailing mengikuti swing terakhir
  (swing low untuk long, swing high untuk short) dengan buffer ATR/percent.
- **Partial take profit**: fraksi posisi ditutup di TP1 dan TP2. Sisa
  disisakan untuk TP3 / hold.
- **Hold decision**: posisi boleh di-hold (skip TP3 close) selama:
    * HTF bias masih searah.
    * Belum muncul CISD lawan arah di LTF.
    * Trailing stop belum tersapu.
  Bila salah satu invalid, force exit walau belum sentuh TP.
- **Invalidations**:
    * Stop-loss / trailing tersapu.
    * CISD lawan arah tercatat (perubahan trend awal).
    * ACR pattern lawan arah muncul di LTF (early warning).

Modul ini pure & deterministic. Input: state posisi + candles terbaru
(LTF & HTF). Output: instance ``PositionUpdate`` dengan aksi konkret.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from typing import Any, Literal

from app.core.models import Candle
from app.indicators.acr import (
    ACRSwing,
    Direction,
    acr_swings,
    cisd_levels,
    latest_acr_pattern,
    latest_cisd,
)


Side = Literal["LONG", "SHORT"]
UpdateAction = Literal[
    "HOLD",              # tidak ada perubahan
    "MOVE_SL",           # geser SL (break-even atau trailing)
    "TAKE_PARTIAL",      # partial close di TP1/TP2
    "EXIT_TP",           # exit penuh di TP3
    "EXIT_SL",           # stop-loss / trailing tersapu
    "EXIT_INVALIDATION", # invalidation karena CISD/pattern lawan arah
    "EXIT_TIME",         # waktu maksimum hold habis (opsional dari caller)
]


DEFAULT_PARTIAL_TP1: float = 0.4   # 40% posisi keluar di TP1
DEFAULT_PARTIAL_TP2: float = 0.35  # 35% posisi keluar di TP2 (sisa 25% untuk TP3/hold)
DEFAULT_TRAIL_BUFFER_PCT: float = 0.002  # 0.2% padding di bawah/atas swing


@dataclass(frozen=True)
class PositionState:
    """Snapshot posisi ACR+ yang sedang aktif.

    Semua field frozen; setiap update menghasilkan ``PositionState`` baru
    melalui :func:`PositionUpdate.next_state`.
    """

    symbol: str
    side: Side
    entry: float
    initial_stop_loss: float
    current_stop_loss: float
    take_profit_1: float
    take_profit_2: float
    take_profit_3: float
    quantity: float                     # size posisi (unit)
    filled_fraction: float = 1.0        # fraksi posisi masih aktif (mulai 1.0)
    tp1_hit: bool = False
    tp2_hit: bool = False
    breakeven_moved: bool = False
    trailing_active: bool = False
    highest_price_seen: float | None = None   # untuk LONG
    lowest_price_seen: float | None = None    # untuk SHORT
    htf_direction: Direction | None = None    # bias saat entry (untuk validasi hold)
    reasons: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PositionUpdate:
    """Hasil satu evaluasi tick position manager."""

    action: UpdateAction
    reasons: list[str]
    new_stop_loss: float | None = None
    close_fraction: float = 0.0          # fraksi posisi yang harus ditutup pada tick ini
    executed_price: float | None = None  # harga eksekusi asumsi (untuk log)
    next_state: PositionState | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["next_state"] = (
            self.next_state.to_dict() if self.next_state else None
        )



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _latest_swing_low(
    candles: list[Candle], after_index: int | None = None
) -> ACRSwing | None:
    swings = acr_swings(candles)
    lows = [s for s in swings if s.side == "LOW"]
    if after_index is not None:
        lows = [s for s in lows if s.index >= after_index]
    return lows[-1] if lows else None


def _latest_swing_high(
    candles: list[Candle], after_index: int | None = None
) -> ACRSwing | None:
    swings = acr_swings(candles)
    highs = [s for s in swings if s.side == "HIGH"]
    if after_index is not None:
        highs = [s for s in highs if s.index >= after_index]
    return highs[-1] if highs else None


def _opposite(direction: Direction | None) -> Direction | None:
    if direction is None:
        return None
    return "BEARISH" if direction == "BULLISH" else "BULLISH"


def _touch_high(state: PositionState, candle: Candle) -> PositionState:
    if state.side == "LONG":
        prev = state.highest_price_seen or state.entry
        new_high = max(prev, candle.high)
        return replace(state, highest_price_seen=new_high)
    prev = state.lowest_price_seen or state.entry
    new_low = min(prev, candle.low)
    return replace(state, lowest_price_seen=new_low)


def _check_stop_hit(state: PositionState, candle: Candle) -> bool:
    if state.side == "LONG":
        return candle.low <= state.current_stop_loss
    return candle.high >= state.current_stop_loss


def _check_tp1_hit(state: PositionState, candle: Candle) -> bool:
    if state.tp1_hit:
        return False
    if state.side == "LONG":
        return candle.high >= state.take_profit_1
    return candle.low <= state.take_profit_1


def _check_tp2_hit(state: PositionState, candle: Candle) -> bool:
    if state.tp2_hit or not state.tp1_hit:
        return False
    if state.side == "LONG":
        return candle.high >= state.take_profit_2
    return candle.low <= state.take_profit_2


def _check_tp3_hit(state: PositionState, candle: Candle) -> bool:
    if not (state.tp1_hit and state.tp2_hit):
        return False
    if state.side == "LONG":
        return candle.high >= state.take_profit_3
    return candle.low <= state.take_profit_3


# ---------------------------------------------------------------------------
# Trailing stop calculation
# ---------------------------------------------------------------------------


def _compute_trailing_stop(
    state: PositionState,
    ltf_candles: list[Candle],
    buffer_pct: float,
) -> float | None:
    """Hitung SL trailing berdasarkan swing terakhir.

    - LONG: SL = swing_low terbaru * (1 - buffer_pct). Hanya boleh naik
      dari current stop loss.
    - SHORT: SL = swing_high terbaru * (1 + buffer_pct). Hanya boleh turun.
    """

    if state.side == "LONG":
        swing = _latest_swing_low(ltf_candles)
        if swing is None:
            return None
        candidate = swing.price * (1 - buffer_pct)
        if candidate <= state.current_stop_loss:
            return None
        # jangan overshoot ke atas current price (agar tidak langsung kena)
        current_price = ltf_candles[-1].close
        if candidate >= current_price:
            return None
        return candidate
    # SHORT
    swing = _latest_swing_high(ltf_candles)
    if swing is None:
        return None
    candidate = swing.price * (1 + buffer_pct)
    if candidate >= state.current_stop_loss:
        return None
    current_price = ltf_candles[-1].close
    if candidate <= current_price:
        return None
    return candidate


# ---------------------------------------------------------------------------
# Hold decision
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HoldEvaluation:
    should_hold: bool
    reasons: list[str]
    invalidation: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_hold(
    state: PositionState,
    ltf_candles: list[Candle],
    htf_candles: list[Candle] | None = None,
) -> HoldEvaluation:
    """Evaluasi apakah posisi masih layak di-hold jangka panjang.

    Aturan:
      1. Wajib ada ``htf_direction`` di state (bias saat entry).
      2. Belum muncul CISD lawan arah di LTF setelah entry.
      3. Belum muncul ACR pattern actionable lawan arah di LTF.
      4. Bila ``htf_candles`` diberikan: bias HTF terkini masih searah.

    Return ``HoldEvaluation`` dengan flag ``should_hold`` dan alasan.
    """

    reasons: list[str] = []
    if state.htf_direction is None:
        return HoldEvaluation(False, ["missing_htf_direction_at_entry"], None)
    reasons.append(f"entry_bias_{state.htf_direction}")

    opposite = _opposite(state.htf_direction)
    if opposite is None:
        return HoldEvaluation(False, reasons + ["invalid_direction"], None)

    # 1. CISD lawan arah di LTF -> invalidation.
    counter_cisds = [c for c in cisd_levels(ltf_candles) if c.direction == opposite]
    if counter_cisds:
        return HoldEvaluation(
            should_hold=False,
            reasons=reasons + ["counter_cisd_detected"],
            invalidation="counter_cisd",
        )

    # 2. ACR pattern lawan arah -> invalidation.
    counter_pattern = latest_acr_pattern(
        ltf_candles, direction=opposite, require_actionable=True
    )
    if counter_pattern is not None:
        return HoldEvaluation(
            should_hold=False,
            reasons=reasons + ["counter_acr_pattern"],
            invalidation="counter_acr_pattern",
        )

    # 3. Bila diberikan HTF candles, cek bias HTF masih searah.
    if htf_candles is not None and len(htf_candles) >= 5:
        # gunakan reused helper dari acr_plus? kita hindari import circular:
        swings = acr_swings(htf_candles[-30:])
        highs = [s for s in swings if s.side == "HIGH"]
        lows = [s for s in swings if s.side == "LOW"]
        if len(highs) >= 2 and len(lows) >= 2:
            hh = highs[-1].price > highs[-2].price
            hl = lows[-1].price > lows[-2].price
            ll = lows[-1].price < lows[-2].price
            lh = highs[-1].price < highs[-2].price
            if state.htf_direction == "BULLISH" and not (hh and hl):
                return HoldEvaluation(
                    should_hold=False,
                    reasons=reasons + ["htf_bias_broken"],
                    invalidation="htf_bias_broken",
                )
            if state.htf_direction == "BEARISH" and not (ll and lh):
                return HoldEvaluation(
                    should_hold=False,
                    reasons=reasons + ["htf_bias_broken"],
                    invalidation="htf_bias_broken",
                )
        reasons.append("htf_bias_intact")

    reasons.append("hold_conditions_met")
    return HoldEvaluation(True, reasons, None)

    if state.side == "LONG":
        return candle.high >= state.take_profit_3
    return candle.low <= state.take_profit_3




# ---------------------------------------------------------------------------
# Main update loop
# ---------------------------------------------------------------------------


def update_position(
    state: PositionState,
    ltf_candles: list[Candle],
    *,
    htf_candles: list[Candle] | None = None,
    partial_tp1: float = DEFAULT_PARTIAL_TP1,
    partial_tp2: float = DEFAULT_PARTIAL_TP2,
    trail_buffer_pct: float = DEFAULT_TRAIL_BUFFER_PCT,
) -> PositionUpdate:
    """Evaluasi satu tick: cek SL/TP dan sesuaikan state.

    Urutan cek (prioritas):
      1. Stop-loss / trailing tersapu -> EXIT_SL.
      2. TP1 hit -> partial close + geser SL ke break-even.
      3. TP2 hit -> partial close + aktivasi trailing.
      4. Trailing update bila aktif.
      5. TP3 hit -> exit sisa posisi (kecuali diputuskan hold).
      6. Invalidation (CISD/pattern lawan arah) -> EXIT_INVALIDATION
         (hanya dicek setelah TP1 agar tidak terlalu cepat exit).
      7. Selain itu HOLD atau MOVE_SL (bila trailing bergerak).
    """

    if not ltf_candles:
        return PositionUpdate("HOLD", ["no_candles"], next_state=state)

    latest = ltf_candles[-1]
    reasons: list[str] = []

    state = _touch_high(state, latest)

    if _check_stop_hit(state, latest):
        return PositionUpdate(
            action="EXIT_SL",
            reasons=[
                "stop_loss_hit_trailing"
                if state.trailing_active
                else "stop_loss_hit_initial"
            ],
            close_fraction=state.filled_fraction,
            executed_price=state.current_stop_loss,
            next_state=replace(state, filled_fraction=0.0),
        )

    new_state = state

    # -------------- TP1 hit -> partial + break-even --------------
    if _check_tp1_hit(new_state, latest):
        close_frac = min(partial_tp1, new_state.filled_fraction)
        breakeven_sl = new_state.entry
        if new_state.side == "LONG":
            new_sl = max(new_state.current_stop_loss, breakeven_sl)
        else:
            new_sl = min(new_state.current_stop_loss, breakeven_sl)
        reasons.extend(["tp1_hit_partial_close", "sl_moved_to_breakeven"])
        new_state = replace(
            new_state,
            tp1_hit=True,
            breakeven_moved=True,
            current_stop_loss=new_sl,
            filled_fraction=new_state.filled_fraction - close_frac,
        )
        return PositionUpdate(
            action="TAKE_PARTIAL",
            reasons=list(reasons),
            new_stop_loss=new_sl,
            close_fraction=close_frac,
            executed_price=state.take_profit_1,
            next_state=new_state,
            meta={"tp_level": "TP1"},
        )

    # -------------- TP2 hit -> partial + aktivasi trailing --------------
    if _check_tp2_hit(new_state, latest):
        close_frac = min(partial_tp2, new_state.filled_fraction)
        trail_candidate = _compute_trailing_stop(
            new_state, ltf_candles, trail_buffer_pct
        )
        if trail_candidate is not None:
            base_sl = trail_candidate
            reasons.append("trailing_activated")
        else:
            base_sl = new_state.take_profit_1
            reasons.append("trailing_fallback_to_tp1")
        if new_state.side == "LONG":
            new_sl = max(new_state.current_stop_loss, base_sl)
        else:
            new_sl = min(new_state.current_stop_loss, base_sl)
        reasons.append("tp2_hit_partial_close")
        new_state = replace(
            new_state,
            tp2_hit=True,
            trailing_active=True,
            current_stop_loss=new_sl,
            filled_fraction=new_state.filled_fraction - close_frac,
        )
        return PositionUpdate(
            action="TAKE_PARTIAL",
            reasons=list(reasons),
            new_stop_loss=new_sl,
            close_fraction=close_frac,
            executed_price=state.take_profit_2,
            next_state=new_state,
            meta={"tp_level": "TP2"},
        )

    # -------------- Trailing update (setelah TP2) --------------
    if new_state.trailing_active:
        trail_candidate = _compute_trailing_stop(
            new_state, ltf_candles, trail_buffer_pct
        )
        if trail_candidate is not None:
            new_state = replace(new_state, current_stop_loss=trail_candidate)
            reasons.append("trailing_stop_updated")

    # -------------- TP3 hit --------------
    if _check_tp3_hit(new_state, latest):
        hold_eval = evaluate_hold(new_state, ltf_candles, htf_candles)
        if hold_eval.should_hold:
            reasons.extend(["tp3_reached_but_holding"] + hold_eval.reasons)
            trail_candidate = _compute_trailing_stop(
                new_state, ltf_candles, trail_buffer_pct
            )
            if trail_candidate is not None:
                if new_state.side == "LONG":
                    if trail_candidate > new_state.current_stop_loss:
                        new_state = replace(
                            new_state,
                            current_stop_loss=trail_candidate,
                            trailing_active=True,
                        )
                        reasons.append("trailing_stop_tightened")
                else:
                    if trail_candidate < new_state.current_stop_loss:
                        new_state = replace(
                            new_state,
                            current_stop_loss=trail_candidate,
                            trailing_active=True,
                        )
                        reasons.append("trailing_stop_tightened")
            action: UpdateAction = "MOVE_SL" if "trailing" in " ".join(reasons) else "HOLD"
            return PositionUpdate(
                action=action,
                reasons=list(reasons),
                new_stop_loss=new_state.current_stop_loss,
                next_state=new_state,
                meta={"tp3_deferred": True, "hold_eval": hold_eval.to_dict()},
            )
        reasons.append("tp3_hit_full_exit")
        return PositionUpdate(
            action="EXIT_TP",
            reasons=reasons + hold_eval.reasons,
            close_fraction=new_state.filled_fraction,
            executed_price=state.take_profit_3,
            next_state=replace(new_state, filled_fraction=0.0),
            meta={"tp_level": "TP3", "hold_eval": hold_eval.to_dict()},
        )

    # -------------- Invalidation (setelah TP1) --------------
    if new_state.tp1_hit:
        hold_eval = evaluate_hold(new_state, ltf_candles, htf_candles)
        if not hold_eval.should_hold and hold_eval.invalidation is not None:
            return PositionUpdate(
                action="EXIT_INVALIDATION",
                reasons=reasons + hold_eval.reasons,
                close_fraction=new_state.filled_fraction,
                executed_price=latest.close,
                next_state=replace(new_state, filled_fraction=0.0),
                meta={"invalidation": hold_eval.invalidation},
            )

    # -------------- HOLD / MOVE_SL --------------
    if reasons:
        return PositionUpdate(
            action="MOVE_SL",
            reasons=reasons,
            new_stop_loss=new_state.current_stop_loss,
            next_state=new_state,
        )
    return PositionUpdate(
        action="HOLD", reasons=["no_change"], next_state=new_state,
    )


__all__ = [
    "DEFAULT_PARTIAL_TP1",
    "DEFAULT_PARTIAL_TP2",
    "DEFAULT_TRAIL_BUFFER_PCT",
    "HoldEvaluation",
    "PositionState",
    "PositionUpdate",
    "Side",
    "UpdateAction",
    "evaluate_hold",
    "update_position",
]
