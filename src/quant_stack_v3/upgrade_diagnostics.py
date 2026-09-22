"""Pure fixed-membership signal and explicit turnover/cost measurements."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import numpy as np
import pandas as pd

from quant_stack.models import Side
from quant_stack_v3.fast_engine import HistoricalFill, HistoricalSnapshot

_COST_COMPONENTS = ("commission", "spread_cost", "slippage_cost", "tax_cost", "transfer_fee")
_ZERO = Decimal("0")


def summarize_fixed_pools(scores: pd.DataFrame, labels: pd.DataFrame, label: str) -> pd.DataFrame:
    """Fix Top20/Bottom20 before joining labels; return one row per T session.

    Scores contain session, symbol, score and the frozen score_rank (1 is best).
    Labels contain session, symbol and the requested forward-return column.
    Missing/nonfinite labels never trigger replacement. Means use observed
    members only, with coverage reported separately; no labels means NaN.
    Pools smaller than 40 can overlap, explicitly counted in the output.
    The legacy comparison reproduces the old finite-label rank threshold,
    including its minimum of 20 valid rows, without modifying that code.
    """
    selected = scores.loc[
        np.isfinite(scores.score), ["session", "symbol", "score", "score_rank"]
    ].copy()
    selected = selected.sort_values(["session", "score_rank", "symbol"], kind="stable")
    selected["fixed_top"] = selected.groupby("session").cumcount() < 20
    selected["fixed_bottom"] = selected.groupby("session").cumcount(ascending=False) < 20
    joined = selected.merge(
        labels.loc[:, ["session", "symbol", label]],
        on=["session", "symbol"],
        how="left",
        validate="one_to_one",
    )
    joined[label] = joined[label].where(np.isfinite(joined[label]))
    rows: list[dict[str, object]] = []
    for session, daily in joined.groupby("session", sort=True):
        top = daily.loc[daily.fixed_top]
        bottom = daily.loc[daily.fixed_bottom]
        valid = daily.loc[daily[label].notna()]
        top_mean = float(top[label].mean())
        bottom_mean = float(bottom[label].mean())
        pool_mean = float(daily[label].mean())
        legacy_bottom = valid.loc[valid.score_rank > len(valid) - 20]
        legacy_spread = (
            float(valid.loc[valid.score_rank <= 20, label].mean() - legacy_bottom[label].mean())
            if len(valid) >= 20
            else float("nan")
        )
        row: dict[str, object] = {
            "session": session,
            "label": label,
            "pool_size": len(daily),
            "pool_label_count": len(valid),
            "pool_coverage": len(valid) / len(daily),
            "top_symbols": tuple(top.symbol),
            "bottom_symbols": tuple(bottom.symbol),
            "top_size": len(top),
            "bottom_size": len(bottom),
            "top_label_count": int(top[label].count()),
            "bottom_label_count": int(bottom[label].count()),
            "top_coverage": float(top[label].count() / len(top)),
            "bottom_coverage": float(bottom[label].count() / len(bottom)),
            "overlapping_members": int((daily.fixed_top & daily.fixed_bottom).sum()),
            "top_mean": top_mean,
            "pool_mean": pool_mean,
            "bottom_mean": bottom_mean,
            "top_minus_pool": top_mean - pool_mean,
            "pool_minus_bottom": pool_mean - bottom_mean,
            "top_minus_bottom": top_mean - bottom_mean,
            "legacy_bottom_label_count": len(legacy_bottom),
            "legacy_top_minus_bottom": legacy_spread,
            "fixed_minus_legacy_spread": top_mean - bottom_mean - legacy_spread,
        }
        rows.append(row)
    return pd.DataFrame(rows)


@dataclass(frozen=True)
class DailyTurnoverCosts:
    """One session, normalized by its preceding close (initial NAV on day one)."""

    session: date
    previous_close_nav: Decimal
    buy_notional: Decimal
    sell_notional: Decimal
    gross_notional: Decimal
    two_sided_turnover: Decimal
    half_turnover: Decimal
    fill_count: int
    costs: dict[str, Decimal]
    total_cost: Decimal
    cost_to_previous_nav: Decimal
    cost_to_gross_notional: Decimal | None


@dataclass(frozen=True)
class TurnoverCostPeriod:
    """Period totals and session averages, including all zero-trade sessions."""

    sessions: int
    fill_count: int
    buy_notional: Decimal
    sell_notional: Decimal
    gross_notional: Decimal
    two_sided_turnover: Decimal
    half_turnover: Decimal
    mean_daily_two_sided_turnover: Decimal
    mean_daily_half_turnover: Decimal
    annualized_two_sided_turnover: Decimal
    annualized_half_turnover: Decimal
    costs: dict[str, Decimal]
    total_cost: Decimal
    cost_component_shares: dict[str, Decimal | None]
    cost_to_gross_notional: Decimal | None
    sum_cost_to_previous_nav: Decimal
    mean_daily_cost_to_previous_nav: Decimal


@dataclass(frozen=True)
class TurnoverCostReport:
    """Pure accounting measurements; no changes to execution or historical data."""

    annualization_sessions: int
    initial_nav: Decimal
    daily: tuple[DailyTurnoverCosts, ...]
    total: TurnoverCostPeriod
    yearly: dict[str, TurnoverCostPeriod]
    legacy_gross_notional_over_mean_close_nav: Decimal


def summarize_turnover_costs(
    fills: Sequence[HistoricalFill],
    snapshots: Sequence[HistoricalSnapshot],
    initial_nav: Decimal,
    annualization_sessions: int = 252,
) -> TurnoverCostReport:
    """Sum actual fill notional and five costs using prior-close NAV denominators.

    ``snapshots`` must contain every session in strictly increasing order.
    The first session uses the supplied pre-period NAV. Two-sided turnover is
    (buy + sell notional) / previous NAV; the half convention divides it by 2.
    Annualization scales the all-session daily mean by annualization_sessions.
    Spread/slippage are attributed costs already embedded in fill prices;
    reporting them here does not debit cash or adjust NAV again.
    """
    if not snapshots or initial_nav <= 0 or annualization_sessions <= 0:
        raise ValueError("nonempty snapshots, positive initial NAV and annualization required")
    sessions = [snapshot.as_of_date for snapshot in snapshots]
    if sessions != sorted(set(sessions)):
        raise ValueError("snapshots must have unique, increasing sessions")
    if any(snapshot.net_asset_value <= 0 for snapshot in snapshots):
        raise ValueError("snapshot NAV must be positive")
    by_session: dict[date, list[HistoricalFill]] = {session: [] for session in sessions}
    for fill in fills:
        if fill.trading_date not in by_session:
            raise ValueError("fill session missing from snapshots")
        by_session[fill.trading_date].append(fill)
    daily: list[DailyTurnoverCosts] = []
    previous_nav = initial_nav
    for snapshot in snapshots:
        session_fills = by_session[snapshot.as_of_date]
        buy = sum((abs(fill.notional) for fill in session_fills if fill.side == Side.BUY), _ZERO)
        sell = sum((abs(fill.notional) for fill in session_fills if fill.side == Side.SELL), _ZERO)
        gross = buy + sell
        costs = {
            component: sum((getattr(fill, component) for fill in session_fills), _ZERO)
            for component in _COST_COMPONENTS
        }
        total_cost = sum(costs.values(), _ZERO)
        two_sided = gross / previous_nav
        daily.append(
            DailyTurnoverCosts(
                snapshot.as_of_date,
                previous_nav,
                buy,
                sell,
                gross,
                two_sided,
                two_sided / 2,
                len(session_fills),
                costs,
                total_cost,
                total_cost / previous_nav,
                total_cost / gross if gross else None,
            )
        )
        previous_nav = snapshot.net_asset_value
    total = _period(daily, annualization_sessions)
    years = sorted({row.session.year for row in daily})
    mean_close_nav = sum((snapshot.net_asset_value for snapshot in snapshots), _ZERO) / len(
        snapshots
    )
    return TurnoverCostReport(
        annualization_sessions,
        initial_nav,
        tuple(daily),
        total,
        {
            str(year): _period(
                [row for row in daily if row.session.year == year], annualization_sessions
            )
            for year in years
        },
        total.gross_notional / mean_close_nav,
    )


def _period(rows: Sequence[DailyTurnoverCosts], annualization: int) -> TurnoverCostPeriod:
    buy = sum((row.buy_notional for row in rows), _ZERO)
    sell = sum((row.sell_notional for row in rows), _ZERO)
    turnover = sum((row.two_sided_turnover for row in rows), _ZERO)
    costs = {
        component: sum((row.costs[component] for row in rows), _ZERO)
        for component in _COST_COMPONENTS
    }
    total_cost = sum(costs.values(), _ZERO)
    normalized_cost = sum((row.cost_to_previous_nav for row in rows), _ZERO)
    mean = turnover / len(rows)
    return TurnoverCostPeriod(
        len(rows),
        sum(row.fill_count for row in rows),
        buy,
        sell,
        buy + sell,
        turnover,
        turnover / 2,
        mean,
        mean / 2,
        mean * annualization,
        mean * annualization / 2,
        costs,
        total_cost,
        {
            component: value / total_cost if total_cost else None
            for component, value in costs.items()
        },
        total_cost / (buy + sell) if buy + sell else None,
        normalized_cost,
        normalized_cost / len(rows),
    )
