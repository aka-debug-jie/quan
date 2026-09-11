"""V2-C residual-alpha causality and net-increment gate."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


class ResidualAlphaError(ValueError):
    """Raised when a residual-alpha experiment would leak or change its baseline contract."""


@dataclass(frozen=True)
class ResidualExample:
    """One model row with explicit feature, label, and executable-time boundaries."""

    symbol: str
    signal_date: date
    feature_available_on: date
    label_end_date: date
    label_available_on: date
    execution_date: date
    deterministic_prediction: Decimal
    realized_label: Decimal

    @property
    def residual_label(self) -> Decimal:
        """Return the realized label net of the frozen deterministic baseline prediction."""
        return self.realized_label - self.deterministic_prediction


@dataclass(frozen=True)
class NetIncrementReport:
    """Same-contract cost-adjusted comparison of V2-C against frozen V2-B."""

    baseline_net_return: Decimal
    model_net_return: Decimal
    net_increment: Decimal
    status: str


REQUIRED_METRICS = frozenset(
    {
        "ic",
        "rank_ic",
        "icir",
        "cagr",
        "annualized_volatility",
        "sharpe_ratio",
        "maximum_drawdown",
        "turnover",
        "trade_count",
        "total_transaction_costs",
        "benchmark_relative_return",
    }
)


def validate_residual_examples(rows: tuple[ResidualExample, ...]) -> None:
    """Reject future features, prematurely available labels, and same-close execution."""
    if not rows:
        raise ResidualAlphaError("residual-alpha requires examples")
    for row in rows:
        if row.feature_available_on > row.signal_date:
            raise ResidualAlphaError("residual features are not available on the signal date")
        if row.execution_date <= row.signal_date:
            raise ResidualAlphaError("residual signal executes no earlier than T+1")
        if row.label_available_on < row.label_end_date:
            raise ResidualAlphaError("residual label is available before its outcome is complete")


def compare_net_increment(
    baseline_gross: Decimal,
    baseline_cost: Decimal,
    model_gross: Decimal,
    model_cost: Decimal,
    *,
    same_universe: bool,
    same_delay: bool,
    same_cost_model: bool,
) -> NetIncrementReport:
    """Compare only like-for-like V2-B and V2-C portfolios after their frozen costs."""
    if not same_universe or not same_delay or not same_cost_model:
        raise ResidualAlphaError(
            "residual-alpha comparison must retain the V2-B execution contract"
        )
    baseline_net = baseline_gross - baseline_cost
    model_net = model_gross - model_cost
    increment = model_net - baseline_net
    return NetIncrementReport(
        baseline_net_return=baseline_net,
        model_net_return=model_net,
        net_increment=increment,
        status="PASS" if increment > 0 else "REJECTED_NO_EDGE",
    )


def validate_residual_metric_schema(metrics: dict[str, Decimal]) -> None:
    """Require the predeclared V2-C predictive and portfolio metrics before evaluation."""
    if set(metrics) != REQUIRED_METRICS:
        raise ResidualAlphaError("residual-alpha metrics differ from the frozen reporting schema")
