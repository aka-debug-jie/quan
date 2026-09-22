"""CLI for the bounded, offline CN quantitative research upgrade."""

from __future__ import annotations

import fcntl
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
    build_signal_attribution,
    build_upgrade_score_cache,
)
from quant_stack_v3.upgrade_economics import build_economic_summary
from quant_stack_v3.upgrade_parallel import run_upgrade_registry_parallel
from quant_stack_v3.upgrade_protocol import (
    ExperimentSpec,
    UpgradeProtocol,
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


@app.command("attribution")
def attribution(
    bars_path: Annotated[Path, typer.Option()],
    scores_path: Annotated[Path, typer.Option()],
    output_root: Annotated[Path, typer.Option()],
) -> None:
    """Build fixed-group, exposure and rank-persistence signal attribution."""
    path, report = build_signal_attribution(bars_path, scores_path, output_root)
    typer.echo(
        json.dumps(
            {"report": path.as_posix(), "status": report["status"]},
            indent=2,
        )
    )


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
    artifact_root.mkdir(parents=True, exist_ok=True)
    lock_handle = (artifact_root / ".upgrade-run.lock").open("a", encoding="utf-8")
    try:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        lock_handle.close()
        raise ValueError("another upgrade run already owns this artifact root") from error
    base = load_protocol(base_protocol_path)
    upgrade = load_upgrade_protocol(upgrade_protocol_path)
    _validate_inputs(
        upgrade,
        bundle_root=bundle_root,
        bundle_sha256=bundle_sha256,
        bars_path=bars_path,
        scores_path=scores_path,
    )
    inputs = UpgradeInputs(
        bundle_root,
        bundle_sha256,
        bars_path,
        scores_path,
        artifact_root,
        base_protocol_path,
        upgrade_protocol_path,
        action_overrides_path,
    )
    fixed_registry = expand_experiment_registry(upgrade)
    results = run_upgrade_registry_parallel(base, _runtime_specs(fixed_registry), inputs)
    references: dict[str, object] = {}
    for strategy_id in ("B00_LIQ20_D20", "A04_AF7_TOP20_D20"):
        result = results[f"{strategy_id}__REAL_T1_1M"]
        if not str(result.get("RESEARCH_VALIDITY", "")).startswith("VALID_"):
            raise ValueError(f"{strategy_id} is not evaluable for independent reference")
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
    scale_candidates = select_scale_candidates(results, upgrade.scale_selection)
    final_registry = expand_experiment_registry(upgrade, scale_candidates)
    if len(final_registry) > len(fixed_registry):
        results = run_upgrade_registry_parallel(base, _runtime_specs(final_registry), inputs)
    robustness_path, robustness = build_robustness_report(results, artifact_root, artifact_root)
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
    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
    lock_handle.close()
    typer.echo(json.dumps({"matrix": matrix_path.as_posix(), **aggregate}, indent=2))


@app.command("report")
def report(matrix_path: Annotated[Path, typer.Option()]) -> None:
    """Print the immutable aggregate used by the human-facing result report."""
    typer.echo(json.dumps(json.loads(matrix_path.read_text(encoding="utf-8")), indent=2))


@app.command("economics")
def economics(
    matrix_path: Annotated[Path, typer.Option()],
    artifact_root: Annotated[Path, typer.Option()],
    output_root: Annotated[Path, typer.Option()],
    old_matrix_path: Annotated[Path | None, typer.Option()] = None,
    old_artifact_root: Annotated[Path | None, typer.Option()] = None,
) -> None:
    """Compile real-run economics and optional V3 before/after evidence."""
    path, report = build_economic_summary(
        matrix_path,
        artifact_root,
        output_root,
        old_matrix_path=old_matrix_path,
        old_artifact_root=old_artifact_root,
    )
    typer.echo(json.dumps({"report": path.as_posix(), "status": report["status"]}, indent=2))


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


def _validate_inputs(
    protocol: UpgradeProtocol,
    *,
    bundle_root: Path,
    bundle_sha256: str,
    bars_path: Path,
    scores_path: Path,
) -> None:
    """Bind CLI paths to the content identities authorized by the protocol."""
    data = protocol.data
    if bundle_sha256 != data.bundle_sha256 or bundle_root.name != data.tree_sha256:
        raise ValueError("upgrade bundle identity is not authorized by the protocol")
    if _file_sha256(bars_path) != data.normalized_bars_sha256:
        raise ValueError("upgrade normalized bars differ from the frozen protocol")
    scores_sha = _file_sha256(scores_path)
    if scores_path.parent.name != scores_sha:
        raise ValueError("upgrade score cache path is not content-addressed")
    report_path = scores_path.with_name("report.json")
    if not report_path.exists():
        raise ValueError("upgrade score cache lacks its build report")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if (
        report.get("status") != "UPGRADE_SIGNALS_COMPLETE"
        or report.get("scores_sha256") != scores_sha
        or report.get("bars_sha256") != data.normalized_bars_sha256
        or report.get("base_scores_sha256") != data.base_scores_sha256
    ):
        raise ValueError("upgrade score cache authorization chain is incomplete")


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
