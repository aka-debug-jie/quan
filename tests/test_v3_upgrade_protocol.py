"""Offline tests for the exact frozen upgrade registry and its run budget."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest
from pydantic import ValidationError

from quant_stack_v3.upgrade_protocol import (
    AUDIT_IDS,
    CANDIDATE_IDS,
    FORBIDDEN_USES,
    REFERENCE_IDS,
    UpgradeProtocol,
    expand_experiment_registry,
    load_upgrade_protocol,
    validate_registry_budget,
)

ROOT = Path(__file__).parents[1]
CONFIG = ROOT / "configs/upgrade/cn_quant_research_upgrade_v1.yaml"


@pytest.fixture
def protocol() -> UpgradeProtocol:
    return load_upgrade_protocol(CONFIG)


def test_frozen_matrix_and_fixed_count(protocol: UpgradeProtocol) -> None:
    registry = expand_experiment_registry(protocol)
    assert len(registry) == 51
    assert Counter(row.group for row in registry) == {"core": 48, "audit": 3}
    assert len({row.experiment_id for row in registry}) == 51
    assert tuple(row.id for row in protocol.references) == REFERENCE_IDS
    assert tuple(row.id for row in protocol.candidates) == CANDIDATE_IDS
    assert tuple(row.id for row in protocol.audits) == AUDIT_IDS
    assert set(protocol.forbidden_uses) == set(FORBIDDEN_USES)
    assert all(row.initial_cash == 1_000_000 for row in registry)
    assert all(row.execution_delay_sessions >= 1 for row in registry)
    assert all(row.scenario_id == "REAL_T1_1M" for row in registry if row.group == "audit")
    assert registry[0].experiment_id == "B00_LIQ20_D20__REAL_T1_1M"
    assert registry[-1].experiment_id == "A05R_AF7_D20_ACTUAL_B40__REAL_T1_1M"


@pytest.mark.parametrize("selected_count,total", [(0, 51), (1, 53), (2, 55)])
def test_scale_budget_is_exact(
    protocol: UpgradeProtocol,
    selected_count: int,
    total: int,
) -> None:
    registry = expand_experiment_registry(protocol, CANDIDATE_IDS[:selected_count])
    assert len(registry) == total
    assert validate_registry_budget(protocol, registry) == total
    scale = tuple(row for row in registry if row.group == "conditional_scale")
    assert len(scale) == 2 * selected_count
    assert all(row.cost_mode == "real" and row.execution_delay_sessions == 1 for row in scale)
    for strategy_id in CANDIDATE_IDS[:selected_count]:
        assert {row.initial_cash for row in scale if row.strategy_id == strategy_id} == {
            500_000,
            5_000_000,
        }


def test_scale_selection_order_does_not_change_registry(protocol: UpgradeProtocol) -> None:
    selected = (CANDIDATE_IDS[1], CANDIDATE_IDS[0])
    assert expand_experiment_registry(protocol, selected) == expand_experiment_registry(
        protocol,
        tuple(reversed(selected)),
    )


@pytest.mark.parametrize(
    "selected,message",
    [
        ((CANDIDATE_IDS[0], CANDIDATE_IDS[0]), "unique"),
        ((REFERENCE_IDS[0],), "only registered candidates"),
        (("UNKNOWN",), "only registered candidates"),
        (CANDIDATE_IDS[:3], "at most two"),
    ],
)
def test_scale_rejects_unregistered_duplicate_and_excess_selections(
    protocol: UpgradeProtocol,
    selected: tuple[str, ...],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        expand_experiment_registry(protocol, selected)


@pytest.mark.parametrize("matrix", ["references", "candidates", "audits"])
def test_strategy_matrix_rejects_missing_duplicate_reordered_and_unknown(
    protocol: UpgradeProtocol,
    matrix: str,
) -> None:
    for kind in ("missing", "duplicate", "reordered", "unknown"):
        value = protocol.model_dump()
        rows = value[matrix]
        if kind == "missing":
            value[matrix] = rows[:-1]
        elif kind == "duplicate":
            value[matrix] = (*rows[:-1], rows[0])
        elif kind == "reordered":
            value[matrix] = tuple(reversed(rows))
        else:
            rows[0]["id"] = "UNREGISTERED"
        with pytest.raises(ValidationError, match="matrix drifted"):
            UpgradeProtocol.model_validate(value)


@pytest.mark.parametrize(
    "hash_field",
    ["bundle_sha256", "tree_sha256", "normalized_bars_sha256"],
)
def test_snapshot_hashes_cannot_drift(protocol: UpgradeProtocol, hash_field: str) -> None:
    value = protocol.model_dump()
    value["data"][hash_field] = "0" * 64
    with pytest.raises(ValidationError):
        UpgradeProtocol.model_validate(value)


@pytest.mark.parametrize("field", ["initial_cash", "execution_delay_sessions", "cost_mode"])
@pytest.mark.parametrize("matrix", ["core_scenarios", "conditional_scale_scenarios"])
def test_scenario_semantics_cannot_drift(
    protocol: UpgradeProtocol,
    matrix: str,
    field: str,
) -> None:
    value = protocol.model_dump()
    value[matrix][0][field] = {
        "initial_cash": 2_000_000,
        "execution_delay_sessions": 2,
        "cost_mode": "zero_all",
    }[field]
    with pytest.raises(ValidationError, match="scenario matrix drifted"):
        UpgradeProtocol.model_validate(value)


@pytest.mark.parametrize("forbidden_use", FORBIDDEN_USES)
def test_every_forbidden_use_is_required(protocol: UpgradeProtocol, forbidden_use: str) -> None:
    value = protocol.model_dump()
    value["forbidden_uses"] = tuple(item for item in FORBIDDEN_USES if item != forbidden_use)
    with pytest.raises(ValidationError, match="forbidden uses"):
        UpgradeProtocol.model_validate(value)


@pytest.mark.parametrize(
    "field",
    [
        "core_runs",
        "audit_runs",
        "maximum_scale_candidates",
        "maximum_scale_runs",
        "maximum_total_runs",
    ],
)
def test_budget_fields_cannot_drift(protocol: UpgradeProtocol, field: str) -> None:
    value = protocol.model_dump()
    value["budget"][field] += 1
    with pytest.raises(ValidationError, match="budget must be exactly"):
        UpgradeProtocol.model_validate(value)


def test_rejects_extra_fields_and_scalar_coercion(protocol: UpgradeProtocol) -> None:
    value = protocol.model_dump()
    value["undeclared"] = True
    with pytest.raises(ValidationError, match="Extra inputs"):
        UpgradeProtocol.model_validate(value)
    value = protocol.model_dump()
    value["budget"]["maximum_total_runs"] = "55"
    with pytest.raises(ValidationError, match="valid integer"):
        UpgradeProtocol.model_validate(value)
    value = protocol.model_dump()
    value["schema_version"] = 2
    with pytest.raises(ValidationError, match="schema version"):
        UpgradeProtocol.model_validate(value)


def test_registry_budget_rejects_same_count_substitution(protocol: UpgradeProtocol) -> None:
    registry = expand_experiment_registry(protocol)
    modified = registry[0].model_copy(update={"initial_cash": 5_000_000})
    with pytest.raises(ValueError, match="semantics drifted"):
        validate_registry_budget(protocol, (modified, *registry[1:]))


def test_registry_budget_rejects_missing_duplicate_excess_and_unpaired(
    protocol: UpgradeProtocol,
) -> None:
    registry = expand_experiment_registry(protocol)
    with pytest.raises(ValueError, match="exactly 48 core and 3 audit"):
        validate_registry_budget(protocol, registry[:-1])
    with pytest.raises(ValueError, match="duplicate"):
        validate_registry_budget(protocol, (*registry, registry[0]))
    maximum = expand_experiment_registry(protocol, CANDIDATE_IDS[:2])
    with pytest.raises(ValueError, match="55-run hard limit"):
        validate_registry_budget(protocol, (*maximum, registry[0]))
    with pytest.raises(ValueError, match="both frozen capital"):
        validate_registry_budget(protocol, maximum[:-1])
    modified = maximum[-1].model_copy(
        update={"strategy_id": REFERENCE_IDS[0], "experiment_id": "unregistered-scale"},
    )
    with pytest.raises(ValueError, match="at most two registered candidates"):
        validate_registry_budget(protocol, (*maximum[:-1], modified))


def test_loader_requires_mapping_and_required_fields(tmp_path: Path) -> None:
    path = tmp_path / "invalid.yaml"
    path.write_text("[]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must be a mapping"):
        load_upgrade_protocol(path)
    path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValidationError, match="Field required"):
        load_upgrade_protocol(path)
