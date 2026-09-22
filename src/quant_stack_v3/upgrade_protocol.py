"""Frozen offline upgrade matrix and deterministic experiment registration."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

REFERENCE_IDS = (
    "B00_LIQ20_D20",
    "A04_AF7_TOP20_D20",
    "B50_LIQ50_D20",
    "B100_LIQ100_D20",
)
CANDIDATE_IDS = (
    "AF7_TOP50_D20_EQ",
    "AF7_TOP50_D20_HOLD100_BAND25",
    "AF7_TOP50_D5_STEP25",
    "AF7_LOW_AVOID100_D20",
    "MOM605_TOP50_D20_EQ",
    "CONDREV5_TOP50_D20_EQ",
    "DOWN60_TOP50_D20_EQ",
    "ROBUSTTREND_TOP50_D20_EQ",
)
AUDIT_IDS = ("A01_AF7_D1", "A02R_AF7_D1_ACTUAL_B40", "A05R_AF7_D20_ACTUAL_B40")
FORBIDDEN_USES = (
    "csi500",
    "sealed_test",
    "paid_data",
    "live_order",
    "paper_deployment",
)
CostMode = Literal["real", "double_assumption", "zero_all"]


class StrictModel(BaseModel):
    """Forbid implicit scalar coercion and unregistered fields."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class UpgradeDataSpec(StrictModel):
    """Exact inherited snapshot identities; this protocol downloads no data."""

    primary: Literal["rqalpha_monthly_bundle_202609"]
    bundle_sha256: Literal["80e1d3287ec2f9f3c255fe648c5487bc4cf5e4186a1dbdb0659939ba7e931139"]
    tree_sha256: Literal["9175506046669b3168003cabd0313fed501d1f9ca4906d7cc083809ae79f2620"]
    normalized_bars_sha256: Literal[
        "d0b4f72f8bc95539582f129ed1ad1e9c22c4dbb49f98413566bec9c1e5a3cc8f"
    ]


class UpgradeStrategySpec(StrictModel):
    """One named, prespecified strategy; descriptions do not tune execution."""

    id: str
    description: str = Field(min_length=1)


class UpgradeScenarioSpec(StrictModel):
    """Capital, causal delay and transaction-cost treatment for one scenario."""

    id: str
    initial_cash: int = Field(gt=0)
    execution_delay_sessions: int = Field(ge=1, le=2)
    cost_mode: CostMode


CORE_SCENARIOS = (
    UpgradeScenarioSpec(
        id="REAL_T1_1M", initial_cash=1_000_000, execution_delay_sessions=1, cost_mode="real"
    ),
    UpgradeScenarioSpec(
        id="DOUBLE_ASSUMPTION_T1_1M",
        initial_cash=1_000_000,
        execution_delay_sessions=1,
        cost_mode="double_assumption",
    ),
    UpgradeScenarioSpec(
        id="ZERO_ALL_COST_T1_1M",
        initial_cash=1_000_000,
        execution_delay_sessions=1,
        cost_mode="zero_all",
    ),
    UpgradeScenarioSpec(
        id="REAL_T2_1M", initial_cash=1_000_000, execution_delay_sessions=2, cost_mode="real"
    ),
)
SCALE_SCENARIOS = (
    UpgradeScenarioSpec(
        id="REAL_T1_500K", initial_cash=500_000, execution_delay_sessions=1, cost_mode="real"
    ),
    UpgradeScenarioSpec(
        id="REAL_T1_5M", initial_cash=5_000_000, execution_delay_sessions=1, cost_mode="real"
    ),
)


class UpgradeBudget(StrictModel):
    """Exact counts, including the optional four-run scale allowance."""

    core_runs: int
    audit_runs: int
    maximum_scale_candidates: int
    maximum_scale_runs: int
    maximum_total_runs: int

    @model_validator(mode="after")
    def exact_budget(self) -> UpgradeBudget:
        """Reject any widening or accidental narrowing of the frozen budget."""
        if (
            self.core_runs,
            self.audit_runs,
            self.maximum_scale_candidates,
            self.maximum_scale_runs,
            self.maximum_total_runs,
        ) != (48, 3, 2, 4, 55):
            raise ValueError("upgrade budget must be exactly 48 + 3 + at most 4 = 55")
        return self


class UpgradeProtocol(StrictModel):
    """Frozen 12-by-four core matrix, three audits and conditional scale runs."""

    schema_version: int
    protocol_id: Literal["CN-QUANT-RESEARCH-UPGRADE-V1"]
    status: Literal["PREREGISTERED_BEFORE_PORTFOLIO_RETURNS"]
    scope: Literal["HISTORICAL_RESEARCH_ONLY"]
    data: UpgradeDataSpec
    references: tuple[UpgradeStrategySpec, ...]
    candidates: tuple[UpgradeStrategySpec, ...]
    audits: tuple[UpgradeStrategySpec, ...]
    core_scenarios: tuple[UpgradeScenarioSpec, ...]
    conditional_scale_scenarios: tuple[UpgradeScenarioSpec, ...]
    budget: UpgradeBudget
    forbidden_uses: tuple[str, ...]

    @model_validator(mode="after")
    def exact_matrix(self) -> UpgradeProtocol:
        """Reject drift in identities, ordering, scenario semantics or prohibitions."""
        if self.schema_version != 1:
            raise ValueError("upgrade schema version must be 1")
        for name, expected in (
            ("references", REFERENCE_IDS),
            ("candidates", CANDIDATE_IDS),
            ("audits", AUDIT_IDS),
        ):
            if tuple(item.id for item in getattr(self, name)) != expected:
                raise ValueError(f"upgrade {name} matrix drifted")
        if self.core_scenarios != CORE_SCENARIOS:
            raise ValueError("upgrade core scenario matrix drifted")
        if self.conditional_scale_scenarios != SCALE_SCENARIOS:
            raise ValueError("upgrade conditional scale scenario matrix drifted")
        if set(self.forbidden_uses) != set(FORBIDDEN_USES) or len(self.forbidden_uses) != 5:
            raise ValueError("upgrade must retain all five frozen forbidden uses")
        return self


class ExperimentSpec(StrictModel):
    """A registered run; registration never executes a backtest."""

    experiment_id: str
    strategy_id: str
    group: Literal["core", "audit", "conditional_scale"]
    scenario_id: str
    initial_cash: int
    execution_delay_sessions: int
    cost_mode: CostMode


def load_upgrade_protocol(path: Path) -> UpgradeProtocol:
    """Load the frozen YAML matrix, accepting YAML sequences as immutable tuples."""
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("upgrade protocol must be a mapping")
    for key in (
        "references",
        "candidates",
        "audits",
        "core_scenarios",
        "conditional_scale_scenarios",
        "forbidden_uses",
    ):
        if isinstance(value.get(key), list):
            value[key] = tuple(value[key])
    return UpgradeProtocol.model_validate(value)


def _experiment(
    strategy_id: str,
    scenario: UpgradeScenarioSpec,
    group: Literal["core", "audit", "conditional_scale"],
) -> ExperimentSpec:
    return ExperimentSpec(
        experiment_id=f"{strategy_id}__{scenario.id}",
        strategy_id=strategy_id,
        group=group,
        scenario_id=scenario.id,
        initial_cash=scenario.initial_cash,
        execution_delay_sessions=scenario.execution_delay_sessions,
        cost_mode=scenario.cost_mode,
    )


def expand_experiment_registry(
    protocol: UpgradeProtocol,
    scale_candidates: tuple[str, ...] = (),
) -> tuple[ExperimentSpec, ...]:
    """Expand 51 fixed runs plus two scale runs per explicitly selected candidate."""
    if len(set(scale_candidates)) != len(scale_candidates):
        raise ValueError("conditional scale candidates must be unique")
    if not set(scale_candidates).issubset(CANDIDATE_IDS):
        raise ValueError("conditional scale selection must contain only registered candidates")
    if len(scale_candidates) > protocol.budget.maximum_scale_candidates:
        raise ValueError("conditional scale permits at most two candidates")
    registry = (
        tuple(
            _experiment(strategy.id, scenario, "core")
            for strategy in (*protocol.references, *protocol.candidates)
            for scenario in protocol.core_scenarios
        )
        + tuple(
            _experiment(strategy.id, protocol.core_scenarios[0], "audit")
            for strategy in protocol.audits
        )
        + tuple(
            _experiment(strategy.id, scenario, "conditional_scale")
            for strategy in protocol.candidates
            if strategy.id in scale_candidates
            for scenario in protocol.conditional_scale_scenarios
        )
    )
    validate_registry_budget(protocol, registry)
    return registry


def validate_registry_budget(
    protocol: UpgradeProtocol,
    registry: tuple[ExperimentSpec, ...],
) -> int:
    """Require exact core/audit coverage and complete paired conditional scale runs."""
    if len(registry) > protocol.budget.maximum_total_runs:
        raise ValueError("experiment registry exceeds the 55-run hard limit")
    if len({item.experiment_id for item in registry}) != len(registry):
        raise ValueError("experiment registry contains duplicate experiment IDs")
    counts = Counter(item.group for item in registry)
    if counts["core"] != protocol.budget.core_runs or counts["audit"] != 3:
        raise ValueError("experiment registry must contain exactly 48 core and 3 audit runs")
    expected_fixed = {
        _experiment(strategy.id, scenario, "core")
        for strategy in (*protocol.references, *protocol.candidates)
        for scenario in protocol.core_scenarios
    } | {_experiment(strategy.id, CORE_SCENARIOS[0], "audit") for strategy in protocol.audits}
    actual_fixed = {item for item in registry if item.group != "conditional_scale"}
    if actual_fixed != expected_fixed:
        raise ValueError("experiment registry fixed matrix or scenario semantics drifted")
    scale = {item for item in registry if item.group == "conditional_scale"}
    selected = {item.strategy_id for item in scale}
    if not selected.issubset(CANDIDATE_IDS) or len(selected) > 2:
        raise ValueError("conditional scale permits at most two registered candidates")
    expected_scale = {
        _experiment(strategy_id, scenario, "conditional_scale")
        for strategy_id in selected
        for scenario in protocol.conditional_scale_scenarios
    }
    if scale != expected_scale:
        raise ValueError("conditional scale requires both frozen capital scenarios per candidate")
    return len(registry)
