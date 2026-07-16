"""Strategi Auden Candle Range Plus (ACR+).

Implementasi checklist ACR+ Entry Model sesuai modul AudenFX Mentorship
(``docs/pdf/ACR - Entry Model.pdf``). Strategi ini murni deterministic:

- Tidak melakukan I/O, tidak menyentuh eksekusi live, tidak menulis file.
- Menghasilkan ``ACRPlusDecision`` (BUY / SELL / HOLD) beserta anchor,
  entry, stop-loss, dua take-profit level, alasan deterministic, dan meta
  lengkap untuk audit/backtest.

Alur high-level per candle (mode close bar, LTF):
    1. Tentukan bias HTF: struktur (Higher-High/Higher-Low untuk BUY, mirror
       untuk SELL) dan zona equilibrium (BUY di discount, SELL di premium).
    2. Cari ACR pattern actionable di LTF searah bias HTF.
    3. Validasi checklist wajib:
         a. CISD searah muncul di sekitar Candle 2 pattern.
         b. Displacement FVG searah setelah CISD.
         c. MSS wick break searah (opsional, jadi confidence).
         d. Reaksi di key level HTF (support / resistance).
    4. Hitung level Entry / SL / TP berdasarkan Entry Model I / II / III:
         - Model I: entry di CISD level.
         - Model II: entry di FVG (mid FVG).
         - Model III: entry di opposing candle Candle 3.
       Otomatis pilih model dengan RR terbaik (>= min_rr).
    5. Tegakkan RR minimum (default 2R sesuai ACR+ notes).

Hard-gates yang menyebabkan HOLD:
    - Tidak ada bias HTF jelas.
    - Tidak ada ACR actionable di LTF.
    - Tidak ada CISD searah.
    - Tidak ada displacement FVG searah setelah CISD.
    - Semua model kandidat gagal memenuhi RR minimum.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from app.core.models import Candle
from app.indicators.acr import (
    ACRPattern,
    CISDLevel,
    Direction,
    EquilibriumRange,
    FairValueGap,
    OpposingCandle,
    acr_swings,
    cisd_levels,
    fair_value_gaps,
    latest_acr_pattern,
    latest_cisd,
    latest_equilibrium_range,
    latest_opposing,
    latest_unfilled_fvg,
    mss_events,
    opposing_candles,
)


Action = Literal["BUY", "SELL", "HOLD"]
EntryModel = Literal["I_CISD", "II_FVG", "III_OPPOSING"]

# --- Konstanta default (bisa di-override lewat parameter) ---
DEFAULT_MIN_RR: float = 2.0            # ACR+ notes: TP fix 2R.
DEFAULT_SL_BUFFER_PCT: float = 0.001   # 0.1% padding beyond wick candle 2.
DEFAULT_HTF_LOOKBACK: int = 30         # candle HTF untuk struktur bias.
DEFAULT_DISPLACEMENT_LOOKFWD: int = 6  # candle setelah CISD untuk cari FVG.


@dataclass(frozen=True)
class ACRPlusContext:
    """Konteks tiga-tier ACR+.

    - ``htf``: timeframe utama untuk bias (Daily/H4 sesuai pair alignment).
    - ``ltf``: timeframe entry (H1/M15/M5 sesuai pair alignment).
    - ``symbol``: simbol pair (dipakai untuk metadata output saja).
    """

    htf: list[Candle]
    ltf: list[Candle]
    symbol: str = "UNKNOWN"
    htf_tf: str = "H4"
    ltf_tf: str = "M15"


@dataclass(frozen=True)
class HTFBias:
    direction: Direction | None       # None = SIDE / tidak jelas
    reason: str
    swing_high: float | None = None
    swing_low: float | None = None
    equilibrium: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ACRPlusDecision:
    action: Action
    reasons: list[str]
    symbol: str
    htf_bias: HTFBias
    entry_model: EntryModel | None = None
    entry: float | None = None
    stop_loss: float | None = None
    take_profit_1: float | None = None    # fixed 2R
    take_profit_2: float | None = None    # next opposing liquidity
    take_profit_3: float | None = None    # extended / hold target
    risk_reward: float | None = None
    strategy: str = "acr_plus"
    anchor: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["htf_bias"] = self.htf_bias.to_dict()
        return payload



# ---------------------------------------------------------------------------
# HTF bias detection
# ---------------------------------------------------------------------------


def _htf_bias(candles: list[Candle], lookback: int = DEFAULT_HTF_LOOKBACK) -> HTFBias:
    """Tentukan bias HTF berdasarkan pola swing recent.

    Aturan (mirroring ACR "Market Structure"):
      - Bullish: 2 swing HIGH terakhir naik + 2 swing LOW terakhir naik (HH+HL).
      - Bearish: 2 swing LOW terakhir turun + 2 swing HIGH terakhir turun (LL+LH).
      - Selain itu = SIDE (no bias).
    """

    if len(candles) < 5:
        return HTFBias(direction=None, reason="htf_insufficient_candles")

    window = candles[-lookback:] if len(candles) > lookback else candles
    swings = acr_swings(window)
    highs = [s for s in swings if s.side == "HIGH"]
    lows = [s for s in swings if s.side == "LOW"]

    eq_range = latest_equilibrium_range(window)
    eq_price = eq_range.equilibrium if eq_range else None
    high_price = eq_range.swing_high if eq_range else None
    low_price = eq_range.swing_low if eq_range else None

    if len(highs) >= 2 and len(lows) >= 2:
        hh = highs[-1].price > highs[-2].price
        hl = lows[-1].price > lows[-2].price
        ll = lows[-1].price < lows[-2].price
        lh = highs[-1].price < highs[-2].price
        if hh and hl:
            return HTFBias(
                direction="BULLISH", reason="htf_hh_hl",
                swing_high=high_price, swing_low=low_price, equilibrium=eq_price,
            )
        if ll and lh:
            return HTFBias(
                direction="BEARISH", reason="htf_ll_lh",
                swing_high=high_price, swing_low=low_price, equilibrium=eq_price,
            )

    return HTFBias(
        direction=None, reason="htf_no_clear_structure",
        swing_high=high_price, swing_low=low_price, equilibrium=eq_price,
    )


# ---------------------------------------------------------------------------
# Confluence collector
# ---------------------------------------------------------------------------


def _collect_confluence(
    ltf: list[Candle], pattern: ACRPattern
) -> dict[str, Any]:
    """Kumpulkan CISD, FVG, MSS, opposing candle di sekitar pattern."""

    dir_ = pattern.direction
    cisds = cisd_levels(ltf)
    fvgs = fair_value_gaps(ltf)
    mss = mss_events(ltf)
    opps = opposing_candles(ltf)

    cisd = latest_cisd(cisds, dir_)

    ref_index = pattern.candle2_index
    disp_fvg: FairValueGap | None = None
    for f in fvgs:
        if f.direction != dir_:
            continue
        if f.left_index < ref_index:
            continue
        if f.filled:
            continue
        disp_fvg = f
    if disp_fvg is None:
        disp_fvg = latest_unfilled_fvg(fvgs, dir_)

    mss_ev = next(
        (
            m
            for m in reversed(mss)
            if m.direction == dir_ and m.break_index >= ref_index
        ),
        None,
    )
    opp_ref = (
        pattern.candle3_index if pattern.candle3_index is not None else ref_index
    )
    opp = latest_opposing(opps, dir_, reference_index=opp_ref)

    return {"cisd": cisd, "fvg": disp_fvg, "mss": mss_ev, "opposing": opp}


# ---------------------------------------------------------------------------
# Entry Model level builders
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Levels:
    model: EntryModel
    entry: float
    stop_loss: float
    tp1: float
    tp2: float
    tp3: float
    rr: float


def _build_levels_long(
    *,
    entry: float,
    pattern: ACRPattern,
    cisd: CISDLevel | None,
    fvg: FairValueGap | None,
    opposing: OpposingCandle | None,
    htf_bias: HTFBias,
    min_rr: float,
    sl_buffer_pct: float,
) -> list[_Levels]:
    """Kalkulasi kandidat entry LONG untuk 3 model ACR.

    - SL common: candle2_wick_far (low candle 2) minus buffer.
      Selalu di bawah entry; jika tidak, model ditolak.
    - TP1 = entry + risk * min_rr (fix 2R sesuai ACR+ notes).
    - TP2 = next opposing liquidity di atas (swing_high HTF bila ada,
      atau opposing candle bearish di atas entry) minimal >= TP1 + risk.
    - TP3 = swing_high HTF (jika sudah dipakai TP2, fallback ke TP2 + risk).
    """

    candidates: list[_Levels] = []
    sl_anchor = pattern.candle2_wick_far
    stop_loss = sl_anchor * (1 - sl_buffer_pct)

    # TP2 base: gunakan swing_high HTF sebagai target liquidity utama.
    htf_high = htf_bias.swing_high

    def _finalize(entry_price: float, model: EntryModel) -> _Levels | None:
        risk = entry_price - stop_loss
        if risk <= 0:
            return None
        tp1 = entry_price + risk * min_rr
        # TP2 = liquidity berikutnya, atau tp1 + risk
        if htf_high is not None and htf_high > tp1:
            tp2 = htf_high
        else:
            tp2 = tp1 + risk
        # TP3 = swing HTF (jika belum dipakai) atau extension
        tp3 = max(tp2 + risk, htf_high or tp2 + risk)
        rr = (tp1 - entry_price) / risk
        if rr + 1e-9 < min_rr:
            return None
        return _Levels(model=model, entry=entry_price, stop_loss=stop_loss,
                       tp1=tp1, tp2=tp2, tp3=tp3, rr=rr)

    # Model I: entry di CISD level.
    if cisd is not None and cisd.price > stop_loss:
        lvl = _finalize(cisd.price, "I_CISD")
        if lvl is not None:
            candidates.append(lvl)

    # Model II: entry di FVG (midpoint FVG bullish).
    if fvg is not None and fvg.direction == "BULLISH":
        entry_fvg = fvg.midpoint
        if entry_fvg > stop_loss:
            lvl = _finalize(entry_fvg, "II_FVG")
            if lvl is not None:
                candidates.append(lvl)

    # Model III: entry di opposing candle bullish (support).
    if opposing is not None and opposing.direction == "BULLISH":
        if opposing.price > stop_loss:
            lvl = _finalize(opposing.price, "III_OPPOSING")
            if lvl is not None:
                candidates.append(lvl)

    # Fallback: entry market pada current price.
    lvl = _finalize(entry, "I_CISD")
    if lvl is not None and not any(c.model == "I_CISD" for c in candidates):
        candidates.append(lvl)

    return candidates


def _build_levels_short(
    *,
    entry: float,
    pattern: ACRPattern,
    cisd: CISDLevel | None,
    fvg: FairValueGap | None,
    opposing: OpposingCandle | None,
    htf_bias: HTFBias,
    min_rr: float,
    sl_buffer_pct: float,
) -> list[_Levels]:
    """Kalkulasi kandidat entry SHORT (mirror _build_levels_long)."""

    candidates: list[_Levels] = []
    sl_anchor = pattern.candle2_wick_far  # high candle 2
    stop_loss = sl_anchor * (1 + sl_buffer_pct)
    htf_low = htf_bias.swing_low

    def _finalize(entry_price: float, model: EntryModel) -> _Levels | None:
        risk = stop_loss - entry_price
        if risk <= 0:
            return None
        tp1 = entry_price - risk * min_rr
        if htf_low is not None and htf_low < tp1:
            tp2 = htf_low
        else:
            tp2 = tp1 - risk
        tp3 = min(tp2 - risk, htf_low or (tp2 - risk))
        rr = (entry_price - tp1) / risk
        if rr + 1e-9 < min_rr:
            return None
        return _Levels(model=model, entry=entry_price, stop_loss=stop_loss,
                       tp1=tp1, tp2=tp2, tp3=tp3, rr=rr)

    if cisd is not None and cisd.price < stop_loss:
        lvl = _finalize(cisd.price, "I_CISD")
        if lvl is not None:
            candidates.append(lvl)

    if fvg is not None and fvg.direction == "BEARISH":
        entry_fvg = fvg.midpoint
        if entry_fvg < stop_loss:
            lvl = _finalize(entry_fvg, "II_FVG")
            if lvl is not None:
                candidates.append(lvl)

    if opposing is not None and opposing.direction == "BEARISH":
        if opposing.price < stop_loss:
            lvl = _finalize(opposing.price, "III_OPPOSING")
            if lvl is not None:
                candidates.append(lvl)

    lvl = _finalize(entry, "I_CISD")
    if lvl is not None and not any(c.model == "I_CISD" for c in candidates):
        candidates.append(lvl)

    return candidates


def _pick_best_level(candidates: list[_Levels]) -> _Levels | None:
    """Pilih model dengan RR tertinggi, tiebreak: preferensi Model I > II > III."""

    if not candidates:
        return None
    order = {"I_CISD": 0, "II_FVG": 1, "III_OPPOSING": 2}
    candidates_sorted = sorted(
        candidates, key=lambda c: (-c.rr, order.get(c.model, 99))
    )
    return candidates_sorted[0]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _hold(
    reason: str, symbol: str, htf_bias: HTFBias, base_reasons: list[str]
) -> ACRPlusDecision:
    return ACRPlusDecision(
        action="HOLD",
        reasons=list(base_reasons) + [reason],
        symbol=symbol,
        htf_bias=htf_bias,
    )


def evaluate(
    ctx: ACRPlusContext,
    *,
    min_rr: float = DEFAULT_MIN_RR,
    sl_buffer_pct: float = DEFAULT_SL_BUFFER_PCT,
    htf_lookback: int = DEFAULT_HTF_LOOKBACK,
) -> ACRPlusDecision:
    """Evaluasi ACR+ untuk konteks tertentu; kembalikan keputusan deterministic.

    Alur:
      1. Bias HTF (HH+HL -> BULLISH, LL+LH -> BEARISH, selain itu HOLD).
      2. Pastikan harga LTF berada di zona equilibrium yang sesuai
         (discount untuk BUY, premium untuk SELL). Bila HTF tidak punya
         equilibrium range, gate ini di-skip.
      3. Cari ACR pattern actionable di LTF searah bias.
      4. Kumpulkan confluence: CISD, displacement FVG, MSS, opposing candle.
         CISD & FVG wajib. MSS & opposing candle jadi bonus konfluensi.
      5. Bangun 3 kandidat entry (Model I/II/III) + fallback current price.
      6. Pilih kandidat dengan RR terbaik >= min_rr.
    """

    symbol = ctx.symbol
    if not ctx.htf or not ctx.ltf:
        return _hold(
            "empty_input_candles",
            symbol,
            HTFBias(direction=None, reason="empty_htf"),
            [],
        )

    htf_bias = _htf_bias(ctx.htf, lookback=htf_lookback)
    base_reasons: list[str] = [f"htf_bias_{htf_bias.reason}"]

    if htf_bias.direction is None:
        return _hold("no_htf_bias", symbol, htf_bias, base_reasons)

    current_price = ctx.ltf[-1].close

    # Gate 1: harga LTF di zona equilibrium yang sesuai bias.
    if htf_bias.equilibrium is not None:
        if htf_bias.direction == "BULLISH" and current_price > htf_bias.equilibrium:
            return _hold("price_not_in_discount", symbol, htf_bias, base_reasons)
        if htf_bias.direction == "BEARISH" and current_price < htf_bias.equilibrium:
            return _hold("price_not_in_premium", symbol, htf_bias, base_reasons)
        base_reasons.append(
            "price_in_discount"
            if htf_bias.direction == "BULLISH"
            else "price_in_premium"
        )

    # Gate 2: ACR pattern actionable searah bias.
    pattern = latest_acr_pattern(ctx.ltf, direction=htf_bias.direction)
    if pattern is None:
        return _hold("no_actionable_acr_pattern", symbol, htf_bias, base_reasons)
    base_reasons.append(f"acr_pattern_{pattern.stage}")

    # Gate 3: confluence CISD + FVG.
    conf = _collect_confluence(ctx.ltf, pattern)
    cisd: CISDLevel | None = conf["cisd"]
    fvg: FairValueGap | None = conf["fvg"]
    mss_ev = conf["mss"]
    opposing: OpposingCandle | None = conf["opposing"]

    if cisd is None:
        return _hold("no_cisd_confluence", symbol, htf_bias, base_reasons)
    base_reasons.append("cisd_present")

    if fvg is None:
        return _hold("no_displacement_fvg", symbol, htf_bias, base_reasons)
    base_reasons.append("displacement_fvg_present")

    if mss_ev is not None:
        base_reasons.append("mss_confirmed")
    if opposing is not None:
        base_reasons.append("opposing_candle_present")

    # Gate 4: susun kandidat level + pilih RR terbaik.
    if htf_bias.direction == "BULLISH":
        candidates = _build_levels_long(
            entry=current_price, pattern=pattern, cisd=cisd, fvg=fvg,
            opposing=opposing, htf_bias=htf_bias,
            min_rr=min_rr, sl_buffer_pct=sl_buffer_pct,
        )
        action: Action = "BUY"
    else:
        candidates = _build_levels_short(
            entry=current_price, pattern=pattern, cisd=cisd, fvg=fvg,
            opposing=opposing, htf_bias=htf_bias,
            min_rr=min_rr, sl_buffer_pct=sl_buffer_pct,
        )
        action = "SELL"

    best = _pick_best_level(candidates)
    if best is None:
        return _hold("all_models_failed_rr", symbol, htf_bias, base_reasons)

    base_reasons.append(f"entry_model_{best.model}")
    base_reasons.append(f"rr_at_least_{min_rr:.1f}")

    anchor: dict[str, Any] = {
        "pattern": pattern.to_dict(),
        "cisd": cisd.to_dict(),
        "fvg": fvg.to_dict(),
    }
    if mss_ev is not None:
        anchor["mss"] = mss_ev.to_dict()
    if opposing is not None:
        anchor["opposing"] = opposing.to_dict()

    meta = {
        "candidates": [asdict(c) for c in candidates],
        "min_rr": min_rr,
        "sl_buffer_pct": sl_buffer_pct,
        "htf_tf": ctx.htf_tf,
        "ltf_tf": ctx.ltf_tf,
        "current_price": current_price,
        "hold_eligible": _is_hold_eligible(htf_bias, pattern, mss_ev),
    }

    return ACRPlusDecision(
        action=action,
        reasons=base_reasons,
        symbol=symbol,
        htf_bias=htf_bias,
        entry_model=best.model,
        entry=best.entry,
        stop_loss=best.stop_loss,
        take_profit_1=best.tp1,
        take_profit_2=best.tp2,
        take_profit_3=best.tp3,
        risk_reward=best.rr,
        anchor=anchor,
        meta=meta,
    )


def _is_hold_eligible(
    htf_bias: HTFBias, pattern: ACRPattern, mss_ev: Any
) -> bool:
    """Kandidat untuk hold jangka panjang (ride the trend).

    Kondisi:
      - HTF bias jelas (BULLISH atau BEARISH).
      - Pattern sudah minimal ``confirmed`` (candle 3 respect equilibrium).
      - MSS terkonfirmasi (indikasi shift trend HTF).
    """

    if htf_bias.direction is None:
        return False
    if pattern.stage not in ("confirmed", "expanded"):
        return False
    return mss_ev is not None


__all__ = [
    "ACRPlusContext",
    "ACRPlusDecision",
    "HTFBias",
    "evaluate",
]
