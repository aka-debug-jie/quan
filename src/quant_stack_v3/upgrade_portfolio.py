"""Frozen portfolio policies for the CN research-upgrade experiment."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pandas as pd


@dataclass(frozen=True)
class PortfolioPolicy:
    """One preregistered, long-only portfolio construction rule."""

    strategy_id: str
    rank_column: str
    selection_count: int
    rebalance_sessions: int
    exit_rank: int | None = None
    weight_band_fraction: Decimal | None = None
    step_fraction: Decimal = Decimal("1")
    liquidity_pool_size: int | None = None
    exclude_worst_count: int = 0


@dataclass(frozen=True)
class SelectionDecision:
    """Selected names and equal target weights at one signal close."""

    symbols: tuple[str, ...]
    weights: dict[str, Decimal]
    retained: frozenset[str]
    excluded_low_score: frozenset[str]


def policy_for(strategy_id: str) -> PortfolioPolicy:
    """Return the exact policy associated with one frozen experiment id."""
    policies = {
        "B00_LIQ20_D20": PortfolioPolicy(strategy_id, "liquidity_rank", 20, 20),
        "A01_AF7_D1": PortfolioPolicy(strategy_id, "score_rank", 20, 1),
        "A02R_AF7_D1_ACTUAL_B40": PortfolioPolicy(strategy_id, "score_rank", 20, 1, exit_rank=40),
        "A04_AF7_TOP20_D20": PortfolioPolicy(strategy_id, "score_rank", 20, 20),
        "A05R_AF7_D20_ACTUAL_B40": PortfolioPolicy(strategy_id, "score_rank", 20, 20, exit_rank=40),
        "B50_LIQ50_D20": PortfolioPolicy(strategy_id, "liquidity_rank", 50, 20),
        "B100_LIQ100_D20": PortfolioPolicy(strategy_id, "liquidity_rank", 100, 20),
        "AF7_TOP50_D20_EQ": PortfolioPolicy(strategy_id, "score_rank", 50, 20),
        "AF7_TOP50_D20_HOLD100_BAND25": PortfolioPolicy(
            strategy_id,
            "score_rank",
            50,
            20,
            exit_rank=100,
            weight_band_fraction=Decimal("0.25"),
        ),
        "AF7_TOP50_D5_STEP25": PortfolioPolicy(
            strategy_id, "score_rank", 50, 5, step_fraction=Decimal("0.25")
        ),
        "AF7_LOW_AVOID100_D20": PortfolioPolicy(
            strategy_id,
            "score_rank",
            80,
            20,
            liquidity_pool_size=100,
            exclude_worst_count=20,
        ),
        "MOM605_TOP50_D20_EQ": PortfolioPolicy(strategy_id, "MOM_60_5_rank", 50, 20),
        "CONDREV5_TOP50_D20_EQ": PortfolioPolicy(strategy_id, "COND_REV_5_rank", 50, 20),
        "COND_FILTER_LIQ50_D20_EQ": PortfolioPolicy(strategy_id, "COND_FILTER_LIQ_rank", 50, 20),
        "DOWN60_TOP50_D20_EQ": PortfolioPolicy(strategy_id, "DOWNSIDE_60_rank", 50, 20),
        "ROBUSTTREND_TOP50_D20_EQ": PortfolioPolicy(strategy_id, "ROBUST_TREND_rank", 50, 20),
    }
    try:
        return policies[strategy_id]
    except KeyError as error:
        raise ValueError(f"unsupported upgrade strategy: {strategy_id}") from error


def select_portfolio(
    daily: pd.DataFrame,
    held_symbols: frozenset[str],
    policy: PortfolioPolicy,
) -> SelectionDecision:
    """Select a target from current ranks and actual post-close holdings."""
    required = {"symbol", policy.rank_column, "liquidity_rank"}
    if required - set(daily.columns):
        raise ValueError("daily score table lacks portfolio columns")
    ranked = daily.loc[daily[policy.rank_column].notna()].sort_values(
        [policy.rank_column, "symbol"], kind="stable"
    )
    if policy.liquidity_pool_size is not None:
        ranked = ranked.loc[ranked["liquidity_rank"] <= policy.liquidity_pool_size]
    if len(ranked) < policy.selection_count + policy.exclude_worst_count:
        raise ValueError("portfolio signal cross-section is too small")
    excluded: frozenset[str] = frozenset()
    if policy.exclude_worst_count:
        worst = ranked.nlargest(policy.exclude_worst_count, policy.rank_column)
        excluded = frozenset(str(value) for value in worst["symbol"])
        ranked = ranked.loc[~ranked["symbol"].isin(excluded)]
    rank = {
        str(row.symbol): int(getattr(row, policy.rank_column))
        for row in ranked.itertuples(index=False)
    }
    retained = frozenset(
        symbol
        for symbol in held_symbols
        if policy.exit_rank is not None and rank.get(symbol, 10**9) <= policy.exit_rank
    )
    retained_ordered = tuple(sorted(retained, key=lambda symbol: (rank[symbol], symbol)))
    additions = tuple(str(value) for value in ranked["symbol"] if str(value) not in retained)
    selected = (*retained_ordered, *additions[: policy.selection_count - len(retained)])
    selected = selected[: policy.selection_count]
    if len(selected) != policy.selection_count:
        raise ValueError("portfolio could not fill its frozen selection count")
    weight = Decimal("1") / Decimal(policy.selection_count)
    return SelectionDecision(
        tuple(selected),
        {symbol: weight for symbol in selected},
        retained,
        excluded,
    )


def apply_weight_policy(
    *,
    current_quantity: Decimal,
    target_quantity: Decimal,
    current_weight: Decimal,
    target_weight: Decimal,
    policy: PortfolioPolicy,
) -> Decimal:
    """Return an intermediate desired quantity after band or gradual rules."""
    if target_quantity == 0:
        if policy.step_fraction < 1:
            return current_quantity + (target_quantity - current_quantity) * policy.step_fraction
        return Decimal("0")
    if policy.weight_band_fraction is not None and current_quantity > 0:
        lower = target_weight * (Decimal("1") - policy.weight_band_fraction)
        upper = target_weight * (Decimal("1") + policy.weight_band_fraction)
        if lower <= current_weight <= upper:
            return current_quantity
    return current_quantity + (target_quantity - current_quantity) * policy.step_fraction


def round_gradual_sell_target(
    current_quantity: Decimal,
    intermediate_target: Decimal,
    *,
    minimum_quantity: Decimal,
    sell_increment: Decimal,
) -> Decimal:
    """Avoid creating odd lots while allowing an existing odd remainder to persist."""
    if not Decimal("0") <= intermediate_target < current_quantity:
        raise ValueError("gradual sell target must reduce a positive holding")
    if intermediate_target < minimum_quantity:
        return Decimal("0")
    sell_quantity = ((current_quantity - intermediate_target) // sell_increment) * sell_increment
    return current_quantity - sell_quantity
