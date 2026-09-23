"""Bounded retrospective repair of the frozen CN upgrade comparison."""

from __future__ import annotations

import json
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Annotated

import typer
import yaml

from quant_stack.research_json import canonical_json
from quant_stack.snapshot import write_immutable
from quant_stack_v3.actions import load_no_participation_overrides
from quant_stack_v3.closure_publication import verify_inherited_evidence_archive
from quant_stack_v3.protocol import load_protocol
from quant_stack_v3.upgrade_cli import _validate_inputs
from quant_stack_v3.upgrade_economics import build_economic_summary
from quant_stack_v3.upgrade_parallel import run_upgrade_registry_parallel
from quant_stack_v3.upgrade_protocol import (
    ExperimentSpec,
    UpgradeScenarioSpec,
    expand_experiment_registry,
    load_upgrade_protocol,
)
from quant_stack_v3.upgrade_reference import audit_reference_run
from quant_stack_v3.upgrade_runner import UpgradeInputs, UpgradeRunSpec
from quant_stack_v3.upgrade_statistics import (
    BENCHMARKS,
    build_robustness_report,
    select_scale_candidates,
)

app = typer.Typer(help="Evidence-repaired historical study; no live or paper deployment.")
CONTROL_ID = "COND_FILTER_LIQ50_D20_EQ"
REFERENCE_IDS = (
    "B00_LIQ20_D20",
    "A04_AF7_TOP20_D20",
    "B50_LIQ50_D20",
    "B100_LIQ100_D20",
    "AF7_LOW_AVOID100_D20",
    "CONDREV5_TOP50_D20_EQ",
    CONTROL_ID,
)


@app.command("preflight")
def preflight(
    old_matrix: Annotated[Path, typer.Option()],
    evidence_root: Annotated[Path, typer.Option()],
    closure_protocol: Annotated[Path, typer.Option()] = Path(
        "configs/closure/cn_research_closure_next_v1.yaml"
    ),
    action_evidence: Annotated[Path, typer.Option()] = Path(
        "configs/closure/action_evidence_v1.yaml"
    ),
) -> None:
    """Verify the inherited matrix, local evidence bytes and fixed run budget."""
    contract = _closure_contract(closure_protocol, old_matrix)
    budget = _mapping(contract["budget"])
    events = load_no_participation_overrides(action_evidence, evidence_root=evidence_root)
    legacy_documents = verify_inherited_evidence_archive(action_evidence, evidence_root)
    upgrade = load_upgrade_protocol(Path("configs/upgrade/cn_quant_research_upgrade_v1.yaml"))
    registered = expand_experiment_registry(upgrade)
    if len(registered) != 51 or int(str(budget["total_runs_maximum"])) != 59:
        raise ValueError("closure experiment budget differs from frozen registration")
    typer.echo(
        json.dumps(
            {
                "status": "CLOSURE_PREFLIGHT_PASS",
                "old_registered_runs": len(registered),
                "rights_events_including_inherited": len(events),
                "verified_inherited_documents": legacy_documents,
                "new_control_scenarios": len(upgrade.core_scenarios),
                "maximum_runs": 59,
                "closure_protocol_sha256": _file_sha256(closure_protocol),
                "action_evidence_sha256": _file_sha256(action_evidence),
            },
            indent=2,
        )
    )


@app.command("run")
def run(
    bundle_root: Annotated[Path, typer.Option()],
    bars_path: Annotated[Path, typer.Option()],
    scores_path: Annotated[Path, typer.Option()],
    old_matrix: Annotated[Path, typer.Option()],
    evidence_root: Annotated[Path, typer.Option()],
    artifact_root: Annotated[Path, typer.Option()],
    closure_protocol: Annotated[Path, typer.Option()] = Path(
        "configs/closure/cn_research_closure_next_v1.yaml"
    ),
    action_evidence: Annotated[Path, typer.Option()] = Path(
        "configs/closure/action_evidence_v1.yaml"
    ),
) -> None:
    """Run the complete frozen revision and one post-result mechanism control."""
    contract = _closure_contract(closure_protocol, old_matrix)
    budget = _mapping(contract["budget"])
    load_no_participation_overrides(action_evidence, evidence_root=evidence_root)
    verify_inherited_evidence_archive(action_evidence, evidence_root)
    base_path = Path("configs/v3/cn_historical_research_v3.yaml")
    upgrade_path = Path("configs/upgrade/cn_quant_research_upgrade_v1.yaml")
    base = load_protocol(base_path)
    upgrade = load_upgrade_protocol(upgrade_path)
    _validate_inputs(
        upgrade,
        bundle_root=bundle_root,
        bundle_sha256=upgrade.data.bundle_sha256,
        bars_path=bars_path,
        scores_path=scores_path,
    )
    original = expand_experiment_registry(upgrade)
    controls = tuple(_control_spec(scenario) for scenario in upgrade.core_scenarios)
    specs = tuple(_runtime_spec(item) for item in original) + controls
    if len(specs) != 55:
        raise ValueError("closure core registry must contain exactly 55 runs")
    inputs = UpgradeInputs(
        bundle_root=bundle_root,
        bundle_sha256=upgrade.data.bundle_sha256,
        bars_path=bars_path,
        scores_path=scores_path,
        artifact_root=artifact_root,
        base_protocol_path=base_path,
        protocol_path=upgrade_path,
        action_overrides_path=action_evidence,
        action_evidence_root=evidence_root,
        closure_protocol_path=closure_protocol,
    )
    artifact_root.mkdir(parents=True, exist_ok=True)
    results = run_upgrade_registry_parallel(
        base, specs, inputs, maximum_workers=int(str(budget["workers_maximum"]))
    )
    scale_candidates = select_scale_candidates(results, upgrade.scale_selection)
    if scale_candidates:
        expanded = expand_experiment_registry(upgrade, scale_candidates)
        scale_specs = tuple(_runtime_spec(item) for item in expanded[len(original) :])
        results.update(
            run_upgrade_registry_parallel(
                base,
                scale_specs,
                inputs,
                maximum_workers=int(str(budget["workers_maximum"])),
            )
        )
    if len(results) > 59:
        raise ValueError("closure run count exceeds frozen budget")
    references: dict[str, object] = {}
    for strategy_id in REFERENCE_IDS:
        result = results[f"{strategy_id}__REAL_T1_1M"]
        if not _valid(result):
            references[strategy_id] = {"status": "NOT_EVALUABLE"}
            continue
        reference_path, reference = audit_reference_run(
            primary_run_root=artifact_root / "runs" / str(result["run_identity"]),
            bundle_root=bundle_root,
            bundle_sha256=upgrade.data.bundle_sha256,
            bars_path=bars_path,
            base_protocol=base,
            output_root=artifact_root,
        )
        references[strategy_id] = {
            "status": reference["status"],
            "sha256": _file_sha256(reference_path),
        }
    statistics_path, statistics = build_robustness_report(results, artifact_root, artifact_root)
    candidate_rows = _mapping(statistics["candidates"])
    old_ids = json.loads(old_matrix.read_text(encoding="utf-8"))["result_identities"]
    lineage = {
        experiment_id: {
            "revision_of": old_ids.get(experiment_id),
            "new_run_identity": result["run_identity"],
            "kind": (
                "EVIDENCE_AND_EXECUTION_ORDER_REPAIR"
                if experiment_id in old_ids
                else "POST_RESULT_CONTROL"
                if experiment_id.startswith(f"{CONTROL_ID}__")
                else "ABSOLUTE_SCALE_DIAGNOSTIC"
            ),
        }
        for experiment_id, result in sorted(results.items())
    }
    aggregate: dict[str, object] = {
        "schema_version": 1,
        "status": "CN_RESEARCH_CLOSURE_NEXT_REAL_RUN_COMPLETE",
        "closure_protocol_sha256": _file_sha256(closure_protocol),
        "action_evidence_sha256": _file_sha256(action_evidence),
        "base_upgrade_matrix_sha256": _file_sha256(old_matrix),
        "registered_runs": len(results),
        "revised_runs": len(original),
        "new_control_runs": len(controls),
        "conditional_scale_runs": len(results) - len(specs),
        "cache_reuse_from_old_study": 0,
        "result_identities": {key: value["run_identity"] for key, value in sorted(results.items())},
        "lineage": lineage,
        "independent_references": references,
        "statistics_sha256": _file_sha256(statistics_path),
        "candidate_outcomes": {
            key: _mapping(value)["outcome"] for key, value in candidate_rows.items()
        },
        "matched_benchmarks": BENCHMARKS | {CONTROL_ID: "B50_LIQ50_D20"},
        "mechanism_control": _mechanism_control(results),
        "scale_candidates": scale_candidates,
        "scale_interpretation": "ABSOLUTE_CAPACITY_DIAGNOSTIC_ONLY",
    }
    encoded = canonical_json(aggregate) + b"\n"
    matrix_sha = sha256(encoded).hexdigest()
    matrix_path = artifact_root / "matrix" / f"{matrix_sha}.json"
    write_immutable(matrix_path, encoded)
    economics_path, _ = build_economic_summary(matrix_path, artifact_root, artifact_root)
    manifest = {
        "schema_version": 1,
        "matrix_sha256": matrix_sha,
        "economics_sha256": _file_sha256(economics_path),
        "statistics_sha256": _file_sha256(statistics_path),
        "registered_runs": len(results),
        "revised_runs": len(original),
        "new_control_runs": len(controls),
        "conditional_scale_runs": len(results) - len(specs),
        "cache_reuse_from_old_study": 0,
        "valid_runs": sum(_valid(item) for item in results.values()),
        "not_evaluable_runs": sum(not _valid(item) for item in results.values()),
        "retained_candidates": sum(
            str(_mapping(value)["outcome"]).startswith("RETAIN_")
            for value in candidate_rows.values()
        ),
        "IMPLEMENTATION_STATUS": "REAL_DATA_REEVALUATION_COMPLETE",
        "RESEARCH_VALIDITY": "RETROSPECTIVE_EVIDENCE_REPAIRED_DEVELOPMENT",
        "ECONOMIC_OUTCOME": "SEE_PAIRED_STATISTICS",
        "DATA_USE_LEVEL": str(contract["data_use_level"]),
        "base_source_commit": "90eb3c5f02b602baa3f22207cb3084aa2e234e0f",
    }
    manifest_bytes = canonical_json(manifest) + b"\n"
    manifest_path = artifact_root / "manifests" / f"{sha256(manifest_bytes).hexdigest()}.json"
    write_immutable(manifest_path, manifest_bytes)
    typer.echo(
        json.dumps(
            {
                "matrix": matrix_path.as_posix(),
                "manifest": manifest_path.as_posix(),
                "economics": economics_path.as_posix(),
                "statistics": statistics_path.as_posix(),
                "registered_runs": len(results),
                "valid_runs": manifest["valid_runs"],
                "not_evaluable_runs": manifest["not_evaluable_runs"],
            },
            indent=2,
        )
    )


def _closure_contract(path: Path, old_matrix: Path) -> dict[str, object]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("protocol_id") != "CN-RESEARCH-CLOSURE-NEXT-V1":
        raise ValueError("closure protocol is invalid")
    if _file_sha256(old_matrix) != payload.get("base_upgrade_matrix_sha256"):
        raise ValueError("closure inherited matrix identity differs")
    upgrade_path = Path("configs/upgrade/cn_quant_research_upgrade_v1.yaml")
    if _file_sha256(upgrade_path) != payload.get("base_upgrade_protocol_sha256"):
        raise ValueError("closure inherited protocol identity differs")
    return payload


def _control_spec(scenario: UpgradeScenarioSpec) -> UpgradeRunSpec:
    return UpgradeRunSpec(
        experiment_id=f"{CONTROL_ID}__{scenario.id}",
        strategy_id=CONTROL_ID,
        scenario_id=scenario.id,
        initial_cash=Decimal(scenario.initial_cash),
        execution_delay_sessions=scenario.execution_delay_sessions,
        cost_mode=scenario.cost_mode,
    )


def _runtime_spec(item: ExperimentSpec) -> UpgradeRunSpec:
    return UpgradeRunSpec(
        item.experiment_id,
        item.strategy_id,
        item.scenario_id,
        Decimal(item.initial_cash),
        item.execution_delay_sessions,
        item.cost_mode,
    )


def _mechanism_control(results: dict[str, dict[str, object]]) -> dict[str, object]:
    ids = ("CONDREV5_TOP50_D20_EQ", CONTROL_ID, "B50_LIQ50_D20")
    selected = {key: results[f"{key}__REAL_T1_1M"] for key in ids}
    if not all(_valid(result) for result in selected.values()):
        return {"status": "NOT_EVALUABLE", "reason": "one or more three-way paths failed"}
    cagr = {
        key: float(str(_mapping(result["metrics"])["cagr"])) for key, result in selected.items()
    }
    return {
        "status": "DESCRIPTIVE_ONLY_POST_RESULT_CONTROL",
        "cagr": cagr,
        "reversal_minus_filter_cagr": cagr[ids[0]] - cagr[ids[1]],
        "filter_minus_b50_cagr": cagr[ids[1]] - cagr[ids[2]],
    }


def _valid(result: dict[str, object]) -> bool:
    return str(result.get("RESEARCH_VALIDITY", "")).startswith("VALID_")


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("closure field must be a mapping")
    return value


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
