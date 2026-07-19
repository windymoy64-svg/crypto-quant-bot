"""Learning Agent — analytics engine that extracts insights from trade history.

Takes all TradeRecords and produces LearningInsight — the "wisdom" that
gets sent to the Decision Maker agent.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
import json
from typing import Any

from app.chart_agent.models import ChartReading
from app.learning_agent.models import (
    ChartObservation,
    LearningInsight,
    PatternInsight,
    RegimeInsight,
    SymbolInsight,
    TradeRecord,
)
from app.learning_agent.store import ChartObservationStore, TradeStore
from app.learning_agent.insight_store import LLMInsightRecord, LLMInsightStore


class LearningAgent:
    """Analyzes trade history and produces actionable insights.

    Pure computation — no I/O except reading from TradeStore.
    Call ``learn()`` to produce a fresh LearningInsight from all stored data.
    """

    def __init__(
        self,
        store: TradeStore | None = None,
        observation_store: ChartObservationStore | None = None,
        llm_client: Any = None,
        llm_model: str | None = None,
        llm_base_url: str = "",
        llm_insight_store: LLMInsightStore | None = None,
    ) -> None:
        self._store = store or TradeStore()
        self._observation_store = observation_store or ChartObservationStore()
        self._llm_client = llm_client
        self._llm_model = llm_model
        self._llm_base_url = llm_base_url
        self._llm_insight_store = llm_insight_store or LLMInsightStore()

    def learn(self) -> LearningInsight:
        """Analyze all stored trades and produce insight."""
        records = self._store.load_all()
        return self._analyze(records)

    def learn_from(self, records: list[TradeRecord]) -> LearningInsight:
        """Analyze a provided list of records (useful for testing)."""
        return self._analyze(records)

    def record_trade(self, record: TradeRecord) -> None:
        """Store a new completed trade for future learning."""
        self._store.save(record)

    def record_chart_reading(
        self,
        reading: ChartReading,
        *,
        stage: str,
        scanner_confidence: float = 0.0,
        scanner_gates_passed: bool = False,
        decision: dict[str, Any] | None = None,
    ) -> ChartObservation:
        """Store raw chart context before/after a decision is made."""
        observation = ChartObservation(
            observation_id=f"{reading.symbol}:{reading.timestamp}:{stage}",
            symbol=reading.symbol,
            timestamp=reading.timestamp,
            stage=stage,  # type: ignore[arg-type]
            scanner_confidence=scanner_confidence,
            scanner_gates_passed=scanner_gates_passed,
            chart_reading=reading.to_dict(),
            decision=decision or {},
        )
        self._observation_store.save(observation)
        return observation

    def _analyze(self, records: list[TradeRecord]) -> LearningInsight:
        if not records:
            insight = self._empty_insight()
            return self._enrich_with_llm(insight, records)

        now = datetime.now(tz=UTC).isoformat()
        wins = [r for r in records if r.is_win]
        losses = [r for r in records if not r.is_win]

        total = len(records)
        winrate = (len(wins) / total) * 100 if total else 0.0
        avg_pnl = sum(r.pnl_percent for r in records) / total if total else 0.0

        gross_wins = sum(r.pnl_absolute for r in wins) if wins else 0.0
        gross_losses = abs(sum(r.pnl_absolute for r in losses)) if losses else 1.0
        profit_factor = gross_wins / gross_losses if gross_losses > 0 else 0.0

        pattern_insights = self._pattern_insights(records)
        regime_insights = self._regime_insights(records)
        symbol_insights = self._symbol_insights(records)

        reliable = [p for p in pattern_insights if p.is_reliable]
        hot = [p.pattern_name for p in reliable if p.winrate >= 65]
        cold = [p.pattern_name for p in reliable if p.winrate < 40]

        best_reg = max(regime_insights, key=lambda r: r.winrate) if regime_insights else None
        worst_reg = min(regime_insights, key=lambda r: r.winrate) if regime_insights else None

        winner_conf = [r.confluence_at_entry for r in wins if r.confluence_at_entry > 0]
        loser_conf = [r.confluence_at_entry for r in losses if r.confluence_at_entry > 0]
        avg_conf_win = sum(winner_conf) / len(winner_conf) if winner_conf else 0.0
        avg_conf_loss = sum(loser_conf) / len(loser_conf) if loser_conf else 0.0
        min_conf_rec = (avg_conf_win + avg_conf_loss) / 2 if (avg_conf_win + avg_conf_loss) > 0 else 50.0

        earliest = min((r.timestamp_entry for r in records), default=now)

        insight = LearningInsight(
            total_trades=total,
            overall_winrate=round(winrate, 1),
            overall_avg_pnl=round(avg_pnl, 3),
            overall_profit_factor=round(profit_factor, 2),
            pattern_insights=pattern_insights,
            regime_insights=regime_insights,
            symbol_insights=symbol_insights,
            hot_patterns=hot,
            cold_patterns=cold,
            best_regime=best_reg.regime if best_reg else "MIXED",
            worst_regime=worst_reg.regime if worst_reg else "MIXED",
            avg_confluence_winners=round(avg_conf_win, 1),
            avg_confluence_losers=round(avg_conf_loss, 1),
            min_confluence_recommended=round(min_conf_rec, 1),
            last_updated=now,
            data_since=earliest,
        )
        return self._enrich_with_llm(insight, records)

    def _enrich_with_llm(
        self, insight: LearningInsight, records: list[TradeRecord]
    ) -> LearningInsight:
        if self._llm_client is None or not self._llm_model:
            insight.meta.setdefault("llm", {"enabled": False, "model": None})
            return insight
        summary = self._llm_input_summary(insight, records)

        # Skip the LLM call when the underlying trade data has not changed
        # since the last stored insight.  Calling the model on an identical
        # input only reproduces a near-duplicate narrative and wastes quota.
        current_fp = self._records_fingerprint(records)
        previous_fp = self._llm_insight_store.latest_input_fingerprint()
        if previous_fp is not None and previous_fp == current_fp:
            latest = self._llm_insight_store.latest()
            insight.meta["llm"] = {
                "enabled": True,
                "model": self._llm_model,
                "latest": (latest or {}).get("output"),
                "stored": False,
                "skipped": "no_new_trades",
            }
            return insight

        try:
            output = self._llm_client.chat_json(
                system=(
                    "You are a read-only trading Learning Agent. Analyze only the "
                    "provided deterministic trade statistics. Do not issue direct "
                    "buy/sell orders. Return compact JSON with keys: summary, "
                    "strengths, weaknesses, recommendations, requires_backtest."
                ),
                user=json.dumps(summary, ensure_ascii=False),
                max_tokens=900,
                temperature=0.2,
            )
            now = datetime.now(tz=UTC).isoformat()
            record = LLMInsightRecord(
                timestamp=now,
                agent="learning",
                provider_base_url=self._llm_base_url,
                model=self._llm_model,
                input_summary=summary,
                output=output,
            )
            self._llm_insight_store.save(record)
            insight.meta["llm"] = {
                "enabled": True,
                "model": self._llm_model,
                "latest": output,
                "stored": True,
            }
        except Exception as exc:  # noqa: BLE001 - LLM must never break learning
            insight.meta["llm"] = {
                "enabled": True,
                "model": self._llm_model,
                "error": str(exc),
                "fallback": "deterministic_learning_only",
            }
        return insight

    def _llm_input_summary(
        self, insight: LearningInsight, records: list[TradeRecord]
    ) -> dict[str, Any]:
        recent = records[-20:]
        return {
            "deterministic_insight": insight.to_dict(),
            "recent_trades": [r.to_dict() for r in recent],
            "record_count": len(records),
            "instructions": (
                "Explain patterns and propose hypotheses only. Any recommendation "
                "must be marked as advisory and requiring backtest before trading."
            ),
        }

    @staticmethod
    def _records_fingerprint(records: list[TradeRecord]) -> tuple[int, str]:
        """Identify the trade dataset: (count, last trade_id)."""
        latest_id = str(records[-1].trade_id) if records else ""
        return (len(records), latest_id)

    def _pattern_insights(self, records: list[TradeRecord]) -> list[PatternInsight]:
        """Group trades by pattern+regime and compute stats."""
        groups: dict[tuple[str, str], list[TradeRecord]] = defaultdict(list)
        for r in records:
            for pattern in r.patterns_at_entry:
                groups[(pattern, r.regime_at_entry)].append(r)

        insights: list[PatternInsight] = []
        for (pattern, regime), trades in groups.items():
            wins = [t for t in trades if t.is_win]
            total = len(trades)
            insights.append(PatternInsight(
                pattern_name=pattern,
                regime=regime,
                total_trades=total,
                win_count=len(wins),
                loss_count=total - len(wins),
                winrate=round((len(wins) / total) * 100, 1) if total else 0.0,
                avg_pnl_percent=round(sum(t.pnl_percent for t in trades) / total, 3) if total else 0.0,
                avg_rr_achieved=round(sum(t.risk_reward_achieved for t in trades) / total, 2) if total else 0.0,
                avg_hold_minutes=round(sum(t.hold_duration_minutes for t in trades) / total, 1) if total else 0.0,
                best_pnl=max((t.pnl_percent for t in trades), default=0.0),
                worst_pnl=min((t.pnl_percent for t in trades), default=0.0),
                last_seen=max((t.timestamp_entry for t in trades), default=""),
            ))
        return sorted(insights, key=lambda i: i.winrate, reverse=True)

    def _regime_insights(self, records: list[TradeRecord]) -> list[RegimeInsight]:
        """Group trades by regime and compute stats."""
        groups: dict[str, list[TradeRecord]] = defaultdict(list)
        for r in records:
            groups[r.regime_at_entry].append(r)

        insights: list[RegimeInsight] = []
        for regime, trades in groups.items():
            wins = [t for t in trades if t.is_win]
            total = len(trades)
            tech_stats: dict[str, list[bool]] = defaultdict(list)
            for t in trades:
                for tech in t.techniques_at_entry:
                    tech_stats[tech].append(t.is_win)
            tech_wr = {
                tech: (sum(res) / len(res)) * 100
                for tech, res in tech_stats.items() if len(res) >= 3
            }
            sorted_t = sorted(tech_wr.items(), key=lambda x: x[1], reverse=True)
            best_t = [x[0] for x in sorted_t[:3]]
            worst_t = [x[0] for x in sorted_t[-3:]] if len(sorted_t) >= 3 else []
            insights.append(RegimeInsight(
                regime=regime,
                total_trades=total,
                winrate=round((len(wins) / total) * 100, 1) if total else 0.0,
                avg_pnl_percent=round(sum(t.pnl_percent for t in trades) / total, 3) if total else 0.0,
                avg_confluence_at_entry=round(
                    sum(t.confluence_at_entry for t in trades) / total, 1) if total else 0.0,
                best_techniques=best_t,
                worst_techniques=worst_t,
                avg_hold_minutes=round(
                    sum(t.hold_duration_minutes for t in trades) / total, 1) if total else 0.0,
            ))
        return sorted(insights, key=lambda i: i.winrate, reverse=True)

    def _symbol_insights(self, records: list[TradeRecord]) -> list[SymbolInsight]:
        """Group trades by symbol and compute stats."""
        groups: dict[str, list[TradeRecord]] = defaultdict(list)
        for r in records:
            groups[r.symbol].append(r)

        insights: list[SymbolInsight] = []
        for symbol, trades in groups.items():
            wins = [t for t in trades if t.is_win]
            total = len(trades)
            buy_wins = sum(1 for t in trades if t.side == "BUY" and t.is_win)
            buy_total = sum(1 for t in trades if t.side == "BUY")
            sell_wins = sum(1 for t in trades if t.side == "SELL" and t.is_win)
            sell_total = sum(1 for t in trades if t.side == "SELL")
            buy_wr = (buy_wins / buy_total) if buy_total else 0
            sell_wr = (sell_wins / sell_total) if sell_total else 0
            preferred = "BUY" if buy_wr >= sell_wr else "SELL"

            regime_g: dict[str, list[TradeRecord]] = defaultdict(list)
            for t in trades:
                regime_g[t.regime_at_entry].append(t)
            regime_wr = {
                reg: sum(1 for t in ts if t.is_win) / len(ts)
                for reg, ts in regime_g.items() if ts
            }
            best_r = max(regime_wr, key=regime_wr.get) if regime_wr else "MIXED"
            worst_r = min(regime_wr, key=regime_wr.get) if regime_wr else "MIXED"

            insights.append(SymbolInsight(
                symbol=symbol,
                total_trades=total,
                winrate=round((len(wins) / total) * 100, 1) if total else 0.0,
                avg_pnl_percent=round(
                    sum(t.pnl_percent for t in trades) / total, 3) if total else 0.0,
                avg_hold_minutes=round(
                    sum(t.hold_duration_minutes for t in trades) / total, 1) if total else 0.0,
                preferred_side=preferred,
                best_regime=best_r,
                worst_regime=worst_r,
            ))
        return sorted(insights, key=lambda i: i.total_trades, reverse=True)

    def _empty_insight(self) -> LearningInsight:
        now = datetime.now(tz=UTC).isoformat()
        return LearningInsight(
            total_trades=0,
            overall_winrate=0.0,
            overall_avg_pnl=0.0,
            overall_profit_factor=0.0,
            pattern_insights=[],
            regime_insights=[],
            symbol_insights=[],
            hot_patterns=[],
            cold_patterns=[],
            best_regime="MIXED",
            worst_regime="MIXED",
            avg_confluence_winners=0.0,
            avg_confluence_losers=0.0,
            min_confluence_recommended=50.0,
            last_updated=now,
            data_since=now,
        )

