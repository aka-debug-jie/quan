"""Strict loader for the frozen CN Historical Research V3 protocol."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

ALPHAS = (
    "CN_REV_001",
    "CN_REV_003",
    "CN_PV_003",
    "CN_RANGE_001",
    "CN_VOL_003",
    "CN_VOL_002",
    "CN_PV_004",
)


class StrictModel(BaseModel):
    """Reject unreviewed protocol fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class DataSpec(StrictModel):
    """Frozen historical source and use boundary."""

    primary: Literal["rqalpha_monthly_bundle_202609"]
    source_url: str
    bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    tree_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    normalized_bars_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fallback: Literal["qlib_cn_community_20260910_signal_only"]
    commercial_use: Literal[False]
    redistribution: Literal[False]


class ResearchSpec(StrictModel):
    """Dates and causal lookback bounds."""

    start: date
    end: date
    touched_development_end: date
    maximum_lookback_sessions: Literal[60]
    minimum_listing_sessions: Literal[252]


class UniverseSpec(StrictModel):
    """Causal dynamic liquidity-universe definition."""

    kind: Literal["dynamic_liquidity_top_n"]
    size: Literal[300]
    minimum_cross_section: Literal[300]
    amount_rank_window: Literal[60]
    minimum_mean_amount_window: Literal[20]
    minimum_mean_amount: Decimal
    exclude_st: Literal[True]
    exclude_suspended: Literal[True]


class SignalSpec(StrictModel):
    """Frozen AF-003 signal definition."""

    model: Literal["equal_weight_zscore"]
    alpha_ids: tuple[str, ...]
    selection_count: Literal[20]
    label: Literal["close[T+2] / close[T+1] - 1"]
    tie_break: Literal["symbol_ascending"]


class ExecutionSpec(StrictModel):
    """Portfolio timing and capital constraints."""

    earliest_delay_sessions: Literal[1]
    initial_cash: Decimal
    long_only: Literal[True]
    leverage: Literal[False]
    maximum_trailing_amount_fraction: Decimal
    order_time_in_force: Literal["execution_session_day"]
    replace_failed_selection: Literal[False]


class CostSpec(StrictModel):
    """Research assumptions plus dated statutory costs."""

    commission_rate: Decimal
    minimum_commission: Decimal
    half_spread_rate: Decimal
    slippage_rate: Decimal
    transfer_fee_before_2022_04_29: Decimal
    transfer_fee_from_2022_04_29: Decimal
    sell_tax_before_2023_08_28: Decimal
    sell_tax_from_2023_08_28: Decimal


class StrategySpec(StrictModel):
    """One main preregistered portfolio configuration."""

    id: str
    kind: Literal["liquidity", "af7"]
    rebalance_sessions: Literal[1, 5, 20]
    exit_rank: Literal[20, 40]


class StressSpec(StrictModel):
    """One prespecified pressure or parameter-neighborhood run."""

    id: str
    base: str
    kind: Literal["friction_x2", "execution_t2", "exit_rank"]
    value: Literal[30, 50] | None = None


class Protocol(StrictModel):
    """Complete decision-fixed V3 protocol."""

    schema_version: Literal[1]
    protocol_id: Literal["CN-HISTORICAL-RESEARCH-V3"]
    status: Literal["PREREGISTERED_BEFORE_PORTFOLIO_RETURNS"]
    scope: Literal["HISTORICAL_RESEARCH_ONLY"]
    data: DataSpec
    research: ResearchSpec
    universe: UniverseSpec
    signal: SignalSpec
    execution: ExecutionSpec
    costs: CostSpec
    strategies: tuple[StrategySpec, ...]
    stress_tests: tuple[StressSpec, ...]
    forbidden_uses: tuple[str, ...]

    @model_validator(mode="after")
    def exact_matrix(self) -> Protocol:
        """Reject changes to selected factors, matrix size, or sealed boundaries."""
        if self.signal.alpha_ids != ALPHAS:
            raise ValueError("V3 must retain the frozen seven AF-003 factors")
        expected = {
            "B00_LIQ20_D20",
            "A01_AF7_D1",
            "A02_AF7_D1_B40",
            "A03_AF7_D5",
            "A04_AF7_D20",
            "A05_AF7_D20_B40",
        }
        if {item.id for item in self.strategies} != expected or len(self.strategies) != 6:
            raise ValueError("V3 main experiment matrix drifted")
        if "csi500" not in self.forbidden_uses or "live_order" not in self.forbidden_uses:
            raise ValueError("V3 must retain CSI500 and live-order prohibitions")
        if not self.research.start <= self.research.touched_development_end < self.research.end:
            raise ValueError("V3 research date partitions are invalid")
        if self.data.normalized_bars_sha256 == self.data.bundle_sha256:
            raise ValueError("normalized bars must have an identity distinct from raw bundle bytes")
        return self


def load_protocol(path: Path) -> Protocol:
    """Load and validate the exact research protocol."""
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("V3 protocol must be a mapping")
    for key in ("alpha_ids",):
        value["signal"][key] = tuple(value["signal"][key])
    for key in ("strategies", "stress_tests", "forbidden_uses"):
        value[key] = tuple(value[key])
    return Protocol.model_validate(value)
