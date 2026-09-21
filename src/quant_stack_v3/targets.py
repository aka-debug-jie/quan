"""Frozen target-selection rules for the six V3 portfolio configurations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pandas as pd

from quant_stack_v3.protocol import StrategySpec


@dataclass(frozen=True)
class TargetSet:
    """One close-derived equal-weight target and its causal liquidity caps."""

    signal_date: date
    strategy_id: str
    symbols: tuple[str, ...]
    weights: dict[str, Decimal]
    maximum_notional: dict[str, Decimal]


def build_targets(
    scores: pd.DataFrame,
    sessions: tuple[date, ...],
    strategy: StrategySpec,
    *,
    selection_count: int,
    liquidity_fraction: Decimal,
) -> tuple[TargetSet, ...]:
    """Build deterministic targets without consulting labels or future tradability."""
    required = {
        "session",
        "symbol",
        "score_rank",
        "liquidity_rank",
        "mean_amount_20",
    }
    if required - set(scores.columns):
        raise ValueError("score table lacks target-generation columns")
    if not sessions or tuple(sorted(set(sessions))) != sessions:
        raise ValueError("target sessions must be unique and ascending")
    selected: tuple[str, ...] = ()
    targets: list[TargetSet] = []
    weight = Decimal("1") / Decimal(selection_count)
    for ordinal, session in enumerate(sessions):
        if ordinal % strategy.rebalance_sessions:
            continue
        daily = scores.loc[scores["session"] == pd.Timestamp(session)].copy()
        if len(daily) < selection_count:
            continue
        rank_column = "liquidity_rank" if strategy.kind == "liquidity" else "score_rank"
        daily = daily.sort_values([rank_column, "symbol"], kind="stable")
        rank = {str(row.symbol): int(getattr(row, rank_column)) for row in daily.itertuples()}
        retained = tuple(
            symbol for symbol in selected if rank.get(symbol, 10**9) <= strategy.exit_rank
        )
        additions = tuple(
            str(symbol) for symbol in daily["symbol"].tolist() if str(symbol) not in retained
        )
        selected = (*retained, *additions[: selection_count - len(retained)])
        selected = tuple(selected[:selection_count])
        if len(selected) != selection_count:
            continue
        amount = {
            str(row.symbol): Decimal(str(row.mean_amount_20))
            for row in daily.loc[daily.symbol.isin(selected)].itertuples()
        }
        targets.append(
            TargetSet(
                session,
                strategy.id,
                selected,
                {symbol: weight for symbol in selected},
                {symbol: amount[symbol] * liquidity_fraction for symbol in selected},
            )
        )
    return tuple(targets)


def target_frame(targets: tuple[TargetSet, ...]) -> pd.DataFrame:
    """Flatten targets for immutable Parquet or JSON artifact publication."""
    return pd.DataFrame(
        [
            {
                "signal_date": target.signal_date,
                "strategy_id": target.strategy_id,
                "symbol": symbol,
                "target_weight": str(target.weights[symbol]),
                "maximum_notional": str(target.maximum_notional[symbol]),
            }
            for target in targets
            for symbol in target.symbols
        ]
    )
