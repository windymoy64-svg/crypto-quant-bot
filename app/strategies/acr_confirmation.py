"""ACR+ Confirmation Bridge.

Adapter minimal-invasif yang membungkus ``acr_plus.evaluate`` untuk dipakai
sebagai **filter/konfirmator** di atas engine strategi existing
(``weighted rule engine`` dan ``liquidity_sr_mtf``).

Cara pakai:

    from app.strategies.acr_confirmation import (
        ACRConfirmation, confirm_signal,
    )

    confirmation = confirm_signal(
        symbol="BTCUSDT",
        signal_action="BUY",       # atau "SELL"
        htf_candles=htf_candles,
        ltf_candles=ltf_candles,
    )

    if confirmation.veto:
        # sinyal di-veto oleh ACR+; lewati eksekusi
        pass
    else:
        # lanjutkan pipeline eksekusi, attach confirmation.to_dict() ke meta
        signal_meta["acr_confirmation"] = confirmation.to_dict()

Semantic keputusan:

- ``align`` : ACR+ menghasilkan aksi searah sinyal utama (BUY-BUY / SELL-SELL).
- ``neutral`` : ACR+ ``HOLD`` (gate tidak lengkap) — sinyal utama dibiarkan
  lolos (default: **tidak veto**), tapi diberi label confidence lebih rendah.
- ``conflict`` : ACR+ menghasilkan aksi lawan arah — sinyal **di-veto**.

Modul ini pure & deterministic. Tidak melakukan I/O.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from app.core.models import Candle
from app.strategies.acr_plus import (
    ACRPlusContext,
    ACRPlusDecision,
    evaluate as acr_evaluate,
)


Alignment = Literal["align", "neutral", "conflict"]


@dataclass(frozen=True)
class ACRConfirmation:
    """Hasil evaluasi konfirmator ACR+ terhadap sinyal utama."""

    signal_action: Literal["BUY", "SELL"]
    acr_action: Literal["BUY", "SELL", "HOLD"]
    alignment: Alignment
    veto: bool
    reasons: list[str]
    acr_decision: dict[str, Any] = field(default_factory=dict)
    confidence_multiplier: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def confirm_signal(
    *,
    symbol: str,
    signal_action: Literal["BUY", "SELL"],
    htf_candles: list[Candle],
    ltf_candles: list[Candle],
    min_rr: float = 2.0,
    veto_on_conflict: bool = True,
    veto_on_neutral: bool = False,
    htf_tf: str = "H4",
    ltf_tf: str = "M15",
) -> ACRConfirmation:
    """Konfirmasi sinyal utama melalui evaluator ACR+.

    Parameter:
      - ``symbol`` : simbol pair.
      - ``signal_action`` : "BUY" atau "SELL" dari strategi utama.
      - ``htf_candles`` / ``ltf_candles`` : window candle multi-timeframe.
      - ``min_rr`` : RR minimum ACR+ (default 2.0).
      - ``veto_on_conflict`` : True (default) → tolak sinyal jika ACR+ lawan arah.
      - ``veto_on_neutral`` : False (default) → biarkan lolos meski ACR+ HOLD.
      - ``htf_tf`` / ``ltf_tf`` : label timeframe untuk audit.

    Return ``ACRConfirmation`` dengan:
      - ``alignment`` : ``align`` / ``neutral`` / ``conflict``.
      - ``veto`` : True jika sinyal harus di-tolak.
      - ``confidence_multiplier`` : faktor pengali untuk confidence (1.0 = tidak
        berubah, 1.15 = ada konfirmasi ACR+ searah, 0.85 = neutral).
      - ``reasons`` : daftar alasan deterministic.
      - ``acr_decision`` : payload ``ACRPlusDecision.to_dict()`` untuk audit.
    """

    if signal_action not in ("BUY", "SELL"):
        return ACRConfirmation(
            signal_action=signal_action,   # type: ignore[arg-type]
            acr_action="HOLD",
            alignment="neutral",
            veto=False,
            reasons=["invalid_signal_action_skip_confirmation"],
        )

    if not htf_candles or not ltf_candles:
        return ACRConfirmation(
            signal_action=signal_action,
            acr_action="HOLD",
            alignment="neutral",
            veto=False,
            reasons=["insufficient_mtf_candles_skip_confirmation"],
        )

    ctx = ACRPlusContext(
        htf=htf_candles,
        ltf=ltf_candles,
        symbol=symbol,
        htf_tf=htf_tf,
        ltf_tf=ltf_tf,
    )
    decision: ACRPlusDecision = acr_evaluate(ctx, min_rr=min_rr)

    reasons = [f"acr_{r}" for r in decision.reasons]

    if decision.action == signal_action:
        alignment: Alignment = "align"
        veto = False
        multiplier = 1.15
        reasons.append("acr_confirms_direction")
    elif decision.action == "HOLD":
        alignment = "neutral"
        veto = veto_on_neutral
        multiplier = 0.85
        reasons.append("acr_neutral_hold")
    else:
        # Lawan arah
        alignment = "conflict"
        veto = veto_on_conflict
        multiplier = 0.0 if veto else 0.70
        reasons.append(f"acr_opposite_action_{decision.action}")

    return ACRConfirmation(
        signal_action=signal_action,
        acr_action=decision.action,
        alignment=alignment,
        veto=veto,
        reasons=reasons,
        acr_decision=decision.to_dict(),
        confidence_multiplier=multiplier,
    )


def enrich_trading_signal(
    signal: Any,
    *,
    htf_candles: list[Candle],
    ltf_candles: list[Candle],
    min_rr: float = 2.0,
    veto_on_conflict: bool = True,
    veto_on_neutral: bool = False,
    htf_tf: str = "H4",
    ltf_tf: str = "M15",
) -> tuple[Any, ACRConfirmation]:
    """Bungkus `TradingSignal` (atau signal dict) dengan konfirmasi ACR+.

    Return tuple ``(enriched_signal, confirmation)``.

    - Jika signal adalah ``TradingSignal`` (frozen dataclass): kembalikan
      *TradingSignal baru* dengan ``meta['acr_confirmation']`` diisi dan
      ``confidence`` dikalikan ``confidence_multiplier``. Bila veto = True,
      ``action`` diubah menjadi ``"SKIP"`` dan ``meta['veto_reason']`` diset.
    - Jika signal adalah dict (payload untuk paper engine): mutasi dict langsung
      pada key ``meta``, ``confidence``, ``action``.

    Signal dengan action selain BUY/SELL dilewati apa adanya.
    """

    action = getattr(signal, "action", None) or (
        signal.get("action") if isinstance(signal, dict) else None
    )
    if action not in ("BUY", "SELL"):
        confirmation = ACRConfirmation(
            signal_action=action if action in ("BUY", "SELL") else "BUY",
            acr_action="HOLD",
            alignment="neutral",
            veto=False,
            reasons=["signal_action_not_buy_or_sell_skip"],
        )
        return signal, confirmation

    symbol = getattr(signal, "symbol", None) or (
        signal.get("symbol") if isinstance(signal, dict) else "UNKNOWN"
    )

    confirmation = confirm_signal(
        symbol=str(symbol),
        signal_action=action,   # type: ignore[arg-type]
        htf_candles=htf_candles,
        ltf_candles=ltf_candles,
        min_rr=min_rr,
        veto_on_conflict=veto_on_conflict,
        veto_on_neutral=veto_on_neutral,
        htf_tf=htf_tf,
        ltf_tf=ltf_tf,
    )

    # ------- Dict path (kompatibel dengan paper engine) -------
    if isinstance(signal, dict):
        meta = dict(signal.get("meta") or {})
        meta["acr_confirmation"] = confirmation.to_dict()
        signal["meta"] = meta
        current_conf = float(signal.get("confidence", 0.0))
        new_conf = round(current_conf * confirmation.confidence_multiplier, 4)
        signal["confidence"] = new_conf
        if confirmation.veto:
            signal["action"] = "SKIP"
            meta["veto_reason"] = f"acr_veto_{confirmation.alignment}"
        return signal, confirmation

    # ------- TradingSignal frozen dataclass path -------
    try:
        from dataclasses import replace as _replace

        meta = dict(getattr(signal, "meta", {}) or {})
        meta["acr_confirmation"] = confirmation.to_dict()
        new_conf = round(
            float(getattr(signal, "confidence", 0.0)) * confirmation.confidence_multiplier,
            4,
        )
        new_action = "SKIP" if confirmation.veto else getattr(signal, "action")
        if confirmation.veto:
            meta["veto_reason"] = f"acr_veto_{confirmation.alignment}"
        enriched = _replace(
            signal,
            action=new_action,
            confidence=new_conf,
            meta=meta,
        )
        return enriched, confirmation
    except Exception:
        return signal, confirmation


__all__ = [
    "ACRConfirmation",
    "Alignment",
    "confirm_signal",
    "enrich_trading_signal",
]
