"""Enrichment layer untuk runtime (``run_realtime.py``).

Mengambil signal dict hasil ``scan_symbol_rankings`` (single TF), lalu:
  1. Fetch HTF candles per symbol dari ``MarketDataService``.
  2. Fetch LTF candles.
  3. Panggil ``enrich_trading_signal`` untuk konfirmasi ACR+.
  4. Inject ``ltf_candles`` ke signal dict agar engine bridge bisa jalan
     (trailing/BE/invalidation swing-based di RealtimePaperTradingEngine).

Konfigurasi opsional di ``configs/realtime.json``::

    "acr_enrichment": {
        "enabled": true,
        "htf_timeframe": "15m",
        "ltf_timeframe": "1m",
        "htf_limit": 60,
        "ltf_limit": 60,
        "min_rr": 2.0,
        "veto_on_conflict": true,
        "veto_on_neutral": false,
        "inject_ltf_candles": true
    }
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.core.models import Candle
from app.strategies.acr_confirmation import enrich_trading_signal


@dataclass(frozen=True)
class ACREnrichmentConfig:
    enabled: bool = False
    htf_timeframe: str = "15m"
    ltf_timeframe: str = "1m"
    entry_timeframes: tuple[str, ...] = ()
    htf_limit: int = 60
    ltf_limit: int = 60
    min_rr: float = 2.0
    veto_on_conflict: bool = True
    veto_on_neutral: bool = False
    inject_ltf_candles: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ACREnrichmentConfig":
        data = data or {}
        return cls(
            enabled=bool(data.get("enabled", False)),
            htf_timeframe=str(data.get("htf_timeframe", "15m")),
            ltf_timeframe=str(data.get("ltf_timeframe", "1m")),
            entry_timeframes=tuple(
                str(value) for value in data.get("entry_timeframes", [])
                if str(value)
            ),
            htf_limit=int(data.get("htf_limit", 60)),
            ltf_limit=int(data.get("ltf_limit", 60)),
            min_rr=float(data.get("min_rr", 2.0)),
            veto_on_conflict=bool(data.get("veto_on_conflict", True)),
            veto_on_neutral=bool(data.get("veto_on_neutral", False)),
            inject_ltf_candles=bool(data.get("inject_ltf_candles", True)),
        )


@dataclass
class ACREnrichmentStats:
    total: int = 0
    aligned: int = 0
    neutral: int = 0
    conflicts: int = 0
    vetoed: int = 0
    skipped: int = 0
    errors: int = 0
    per_symbol: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _candle_to_dict(c: Candle) -> dict[str, Any]:
    return {
        "symbol": c.symbol,
        "timestamp": c.timestamp,
        "open": c.open,
        "high": c.high,
        "low": c.low,
        "close": c.close,
        "volume": c.volume,
    }


def _fetch_candles_safe(
    market_data: Any,
    symbol: str,
    *,
    timeframe: str,
    limit: int,
    logger: Any = None,
) -> list[Candle]:
    """Fetch OHLCV dengan error handling."""
    try:
        loaded = market_data.fetch_ohlcv(
            symbol=symbol,
            timeframe=timeframe,
            limit=limit,
            force_refresh=False,
        )
        return list(getattr(loaded, "candles", []) or [])
    except Exception as exc:  # noqa: BLE001
        if logger is not None:
            logger.warning(
                "ACR fetch OHLCV failed %s @%s: %s", symbol, timeframe, exc,
            )
        return []


def enrich_realtime_signals(
    signals: list[dict[str, Any]],
    *,
    market_data: Any,
    config: ACREnrichmentConfig,
    logger: Any = None,
) -> tuple[list[dict[str, Any]], ACREnrichmentStats]:
    """Enrich signal dict hasil scan dengan konfirmasi ACR+ + inject ltf_candles.

    Return: ``(enriched_signals, stats)``.

    Behavior:
      - Bila ``config.enabled=False``, return signals + stats kosong.
      - Bila fetch OHLCV gagal, signal lolos apa adanya (skipped, tidak crash).
      - Signal dengan ``action`` bukan BUY/SELL dilewati untuk enrichment,
        tapi ``ltf_candles`` tetap di-inject bila diminta (agar position
        manager engine bisa jalan pada tick harga).
      - Veto conflict: signal.action → "SKIP".
    """

    stats = ACREnrichmentStats()

    if not config.enabled:
        return signals, stats

    enriched: list[dict[str, Any]] = []

    # Cache OHLCV per (symbol, tf) agar tidak double-fetch dalam 1 siklus.
    cache: dict[tuple[str, str], list[Candle]] = {}

    def _get(symbol: str, tf: str, limit: int) -> list[Candle]:
        key = (symbol, tf)
        if key not in cache:
            cache[key] = _fetch_candles_safe(
                market_data, symbol, timeframe=tf, limit=limit, logger=logger,
            )
        return cache[key]

    for signal in signals:
        stats.total += 1
        action = str(signal.get("action", "")).upper()
        symbol = str(signal.get("symbol", ""))

        if action not in ("BUY", "SELL"):
            # Bukan sinyal directional; forward. Inject ltf_candles bila diminta.
            if config.inject_ltf_candles and symbol:
                ltf_candles = _get(
                    symbol, config.ltf_timeframe, config.ltf_limit
                )
                if ltf_candles:
                    signal["ltf_candles"] = [
                        _candle_to_dict(c) for c in ltf_candles
                    ]
            enriched.append(signal)
            stats.skipped += 1
            continue

        htf_candles = _get(symbol, config.htf_timeframe, config.htf_limit)
        selected_ltf = config.ltf_timeframe
        ltf_candles = _get(symbol, selected_ltf, config.ltf_limit)

        # Evaluate every configured entry timeframe with the same HTF context.
        # Prefer 5m when it has a complete aligned ACR setup; otherwise use 15m.
        # A timeframe is never selected merely because its latest candle moved.
        for candidate_tf in config.entry_timeframes:
            candidate_candles = _get(symbol, candidate_tf, config.ltf_limit)
            if not candidate_candles:
                continue
            try:
                _, candidate_confirmation = enrich_trading_signal(
                    dict(signal),
                    htf_candles=htf_candles,
                    ltf_candles=candidate_candles,
                    min_rr=config.min_rr,
                    veto_on_conflict=config.veto_on_conflict,
                    veto_on_neutral=config.veto_on_neutral,
                    htf_tf=config.htf_timeframe,
                    ltf_tf=candidate_tf,
                )
            except Exception:  # noqa: BLE001 - next timeframe may still qualify
                continue
            if candidate_confirmation.alignment == "align":
                selected_ltf = candidate_tf
                ltf_candles = candidate_candles
                break

        if not htf_candles or not ltf_candles:
            stats.errors += 1
            stats.per_symbol[symbol] = "fetch_failed"
            enriched.append(signal)
            continue

        if config.inject_ltf_candles:
            signal["ltf_candles"] = [_candle_to_dict(c) for c in ltf_candles]
        signal["entry_timeframe"] = selected_ltf
        signal_meta = signal.get("meta")
        if not isinstance(signal_meta, dict):
            signal_meta = {}
            signal["meta"] = signal_meta
        signal_meta["timeframe_context"] = {
            "htf": config.htf_timeframe,
            "entry": selected_ltf,
            "candidates": list(config.entry_timeframes) or [config.ltf_timeframe],
        }

        try:
            enriched_sig, confirmation = enrich_trading_signal(
                signal,
                htf_candles=htf_candles,
                ltf_candles=ltf_candles,
                min_rr=config.min_rr,
                veto_on_conflict=config.veto_on_conflict,
                veto_on_neutral=config.veto_on_neutral,
                htf_tf=config.htf_timeframe,
                ltf_tf=selected_ltf,
            )
        except Exception as exc:  # noqa: BLE001
            stats.errors += 1
            stats.per_symbol[symbol] = f"enrich_error:{type(exc).__name__}"
            if logger is not None:
                logger.warning(
                    "ACR enrichment error for %s: %s", symbol, exc,
                )
            enriched.append(signal)
            continue

        alignment = confirmation.alignment
        if alignment == "align":
            stats.aligned += 1
        elif alignment == "neutral":
            stats.neutral += 1
        elif alignment == "conflict":
            stats.conflicts += 1
        if confirmation.veto:
            stats.vetoed += 1
        stats.per_symbol[symbol] = (
            f"{alignment}{'_veto' if confirmation.veto else ''}"
        )

        if isinstance(enriched_sig, dict):
            enriched.append(enriched_sig)
        else:
            enriched.append(signal)

    return enriched, stats


__all__ = [
    "ACREnrichmentConfig",
    "ACREnrichmentStats",
    "enrich_realtime_signals",
]

