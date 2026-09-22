"""CLI for the bounded, offline CN quantitative research upgrade."""

from __future__ import annotations

import json
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Annotated

import typer

from quant_stack.research_json import canonical_json
from quant_stack.snapshot import write_immutable
from quant_stack_v3.protocol import load_protocol
from quant_stack_v3.upgrade_artifacts import (
    build_measurement_audit,
    build_upgrade_score_cache,
)
from quant_stack_v3.upgrade_parallel import run_upgrade_registry_parallel
from quant_stack_v3.upgrade_protocol import (
    ExperimentSpec,
    expand_experiment_registry,
    load_upgrade_protocol,
)
from quant_stack_v3.upgrade_reference import audit_reference_run
from quant_stack_v3.upgrade_runner import (
    UpgradeInputs,
    UpgradeRunSpec,
)
from quant_stack_v3.upgrade_statistics import (
    build_robustness_report,
    select_scale_candidates,
)

app = typer.Typer(help="Preregistered CN research upgrade; offline and non-deploying only.")


@app.command("preflight")
def preflight(
    protocol_path: Annotated[Path, typer.Option()] = Path(
        "configs/upgrade/cn_quant_research_upgrade_v1.yaml"
    ),
) -> None:
    """Validate the immutable 51+4 experiment budget without reading returns."""
    protocol = load_upgrade_protocol(protocol_path)
    fixed = expand_experiment_registry(protocol)
    maximum = expand_experiment_registry(
        protocol, tuple(item.id for item in protocol.candidates[:2])
    )
    typer.echo(
        json.dumps(
            {
                "protocol_sha256": _file_sha256(protocol_path),
                "status": protocol.status,
                "fixed_runs": len(fixed),
                "maximum_runs": len(maximum),
            },
            indent=2,
        )
    )


@app.command("build-signals")
def build_signals(
    bars_path: Annotated[Path, typer.Option()],
    base_scores_path: Annotated[Path, typer.Option()],
    output_root: Annotated[Path, typer.Option()],
) -> None:
    """Build the four frozen mechanisms and risk exposures once."""
    scores, report_path, report = build_upgrade_score_cache(
        bars_path, base_scores_path, output_root
    )
    typer.echo(
        json.dumps(
            {"scores": scores.as_posix(), "report": report_path.as_posix(), **report},
            indent=2,
        )
    )


@app.command("audit")
def audit(
    bars_path: Annotated[Path, typer.Option()],
    scores_path: Annotated[Path, typer.Option()],
    output_root: Annotated[Path, typer.Option()],
) -> None:
    """Reproduce and correct the fixed-membership label boundary."""
    path, report = build_measurement_audit(bars_path, scores_path, output_root)
    typer.echo(json.dumps({"report": path.as_posix(), **report}, indent=2))


@app.command("run")
def run(
    bundle_root: Annotated[Path, typer.Option()],
    bars_path: Annotated[Path, typer.Option()],
    scores_path: Annotated[Path, typer.Option()],
    artifact_root: Annotated[Path, typer.Option()],
    bundle_sha256: Annotated[str, typer.Option()],
    base_protocol_path: Annotated[Path, typer.Option()] = Path(
        "configs/v3/cn_historical_research_v3.yaml"
    ),
    upgrade_protocol_path: Annotated[Path, typer.Option()] = Path(
        "configs/upgrade/cn_quant_research_upgrade_v1.yaml"
    ),
    action_overrides_path: Annotated[Path, typer.Option()] = Path(
        "configs/v3/corporate_action_overrides_v1.yaml"
    ),
) -> None:
    """Run the exact matrix, conditional scale gate, references and robustness report."""
    base = load_protocol(base_protocol_path)
    upgrade = load_upgrade_protocol(upgrade_protocol_path)
    inputs = UpgradeInputs(
        bundle_root,
        bundle_sha256,
        bars_path,
        scores_path,
        artifact_root,
        upgrade_protocol_path,
        action_overrides_path,
    )
    fixed_registry = expand_experiment_registry(upgrade)
    results = run_upgrade_registry_parallel(base, _runtime_specs(fixed_registry), inputs)
    scale_candidates = select_scale_candidates(results, artifact_root)
    final_registry = expand_experiment_registry(upgrade, scale_candidates)
    if len(final_registry) > len(fixed_registry):
        results = run_upgrade_registry_parallel(base, _runtime_specs(final_registry), inputs)
    robustness_path, robustness = build_robustness_report(results, artifact_root, artifact_root)
    references: dict[str, object] = {}
    for strategy_id in ("B00_LIQ20_D20", "A04_AF7_TOP20_D20"):
        result = results[f"{strategy_id}__REAL_T1_1M"]
        reference_path, reference = audit_reference_run(
            primary_run_root=artifact_root / "runs" / str(result["run_identity"]),
            bundle_root=bundle_root,
            bundle_sha256=bundle_sha256,
            bars_path=bars_path,
            base_protocol=base,
            output_root=artifact_root,
        )
        references[strategy_id] = {
            "path": reference_path.as_posix(),
            "status": reference["status"],
        }
    aggregate: dict[str, object] = {
        "schema_version": 1,
        "status": "CN_QUANT_RESEARCH_UPGRADE_COMPLETE",
        "protocol_sha256": _file_sha256(upgrade_protocol_path),
        "registered_runs": len(final_registry),
        "scale_candidates": scale_candidates,
        "result_identities": {key: value["run_identity"] for key, value in sorted(results.items())},
        "robustness_path": robustness_path.as_posix(),
        "candidate_outcomes": {
            key: _mapping(value)["outcome"]
            for key, value in _mapping(robustness["candidates"]).items()
        },
        "independent_references": references,
    }
    encoded = canonical_json(aggregate) + b"\n"
    matrix_path = artifact_root / "matrix" / f"{sha256(encoded).hexdigest()}.json"
    write_immutable(matrix_path, encoded)
    typer.echo(json.dumps({"matrix": matrix_path.as_posix(), **aggregate}, indent=2))


@app.command("report")
def report(matrix_path: Annotated[Path, typer.Option()]) -> None:
    """Print the immutable aggregate used by the human-facing result report."""
    typer.echo(json.dumps(json.loads(matrix_path.read_text(encoding="utf-8")), indent=2))


@app.command("verify")
def verify(matrix_path: Annotated[Path, typer.Option()]) -> None:
    """Verify one aggregate content hash and its two reference-pass statuses."""
    payload = json.loads(matrix_path.read_text(encoding="utf-8"))
    references = _mapping(payload["independent_references"])
    if set(references) != {"B00_LIQ20_D20", "A04_AF7_TOP20_D20"} or any(
        _mapping(item).get("status") != "INDEPENDENT_ECONOMIC_REFERENCE_PASS"
        for item in references.values()
    ):
        raise typer.Exit(1)
    typer.echo(
        json.dumps(
            {
                "matrix_sha256": _file_sha256(matrix_path),
                "status": "UPGRADE_REFERENCE_VERIFICATION_PASS",
            },
            indent=2,
        )
    )


def _runtime_specs(values: tuple[ExperimentSpec, ...]) -> tuple[UpgradeRunSpec, ...]:
    return tuple(
        UpgradeRunSpec(
            value.experiment_id,
            value.strategy_id,
            value.scenario_id,
            Decimal(value.initial_cash),
            value.execution_delay_sessions,
            value.cost_mode,
        )
        for value in values
    )


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("upgrade CLI field must be a mapping")
    return value


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
