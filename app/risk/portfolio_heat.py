"""Portfolio-level risk guard: total portfolio heat and correlation cap.

Per-trade risk caps do not stop the bot from opening many small positions that
together exceed a sane total risk budget. ``PortfolioHeatGuard`` aggregates the
risk amount of every open position and rejects a new entry when total active
risk exceeds ``max_portfolio_heat_percent`` of equity, or when too many
positions share the same direction / correlated base cluster.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class PortfolioHeatCheck:
    valid: bool
    reason: str
    total_risk_amount: float
    total_risk_percent: float
    max_portfolio_heat_percent: float
    long_positions: int
    short_positions: int
    correlated_clusters: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class OpenPositionRisk:
    symbol: str
    side: str
    risk_amount: float
    cluster: str = ""


def base_cluster(symbol: str) -> str:
    """Coarse correlation cluster from symbol base asset.

    Intentionally simple: stablecoins, BTC/ETH majors, and per-base clusters.
    Upgrade path: replace with a correlation matrix once enough trade history
    exists. ``ponytail: cluster heuristic, add covariance matrix when N>=200``.
    """
    base = str(symbol).upper().replace("-", "/").split("/", 1)[0]
    stables = {"USDC", "FDUSD", "TUSD", "BUSD", "DAI", "USDP", "PYUSD", "USD1"}
    if base in stables:
        return "STABLE"
    if base in {"BTC", "WBTC"}:
        return "BTC"
    if base in {"ETH", "WETH", "STETH"}:
        return "ETH"
    return base


class PortfolioHeatGuard:
    def __init__(
        self,
        max_portfolio_heat_percent: float = 2.0,
        max_per_cluster: int = 2,
        max_same_direction: int = 3,
    ) -> None:
        self.max_portfolio_heat_percent = max_portfolio_heat_percent
        self.max_per_cluster = max_per_cluster
        self.max_same_direction = max_same_direction

    def validate(
        self,
        *,
        equity: float,
        open_positions: list[OpenPositionRisk],
        candidate: OpenPositionRisk,
    ) -> PortfolioHeatCheck:
        positions = [*open_positions, candidate]
        total_risk = sum(max(p.risk_amount, 0.0) for p in positions)
        heat_percent = (
            (total_risk / equity) * 100 if equity > 0 else 0.0
        )

        long_count = sum(
            1 for p in positions if str(p.side).upper() in {"BUY", "LONG"}
        )
        short_count = sum(
            1 for p in positions if str(p.side).upper() in {"SELL", "SHORT"}
        )
        candidate_dir = (
            "LONG" if str(candidate.side).upper() in {"BUY", "LONG"} else "SHORT"
        )
        same_direction = (
            long_count if candidate_dir == "LONG" else short_count
        )

        clusters: dict[str, int] = {}
        for pos in positions:
            key = pos.cluster or base_cluster(pos.symbol)
            clusters[key] = clusters.get(key, 0) + 1
        correlated_clusters = sum(1 for count in clusters.values() if count > 1)
        candidate_cluster_count = clusters.get(
            candidate.cluster or base_cluster(candidate.symbol), 0
        )

        if heat_percent > self.max_portfolio_heat_percent:
            return PortfolioHeatCheck(
                False, "portfolio_heat_exceeded", round(total_risk, 8),
                round(heat_percent, 4), self.max_portfolio_heat_percent,
                long_count, short_count, correlated_clusters,
            )
        if same_direction > self.max_same_direction:
            return PortfolioHeatCheck(
                False, f"{candidate_dir.lower()}_direction_cap",
                round(total_risk, 8), round(heat_percent, 4),
                self.max_portfolio_heat_percent, long_count, short_count,
                correlated_clusters,
            )
        if candidate_cluster_count > self.max_per_cluster:
            return PortfolioHeatCheck(
                False, "correlation_cap_exceeded", round(total_risk, 8),
                round(heat_percent, 4), self.max_portfolio_heat_percent,
                long_count, short_count, correlated_clusters,
            )
        return PortfolioHeatCheck(
            True, "ok", round(total_risk, 8), round(heat_percent, 4),
            self.max_portfolio_heat_percent, long_count, short_count,
            correlated_clusters,
        )
