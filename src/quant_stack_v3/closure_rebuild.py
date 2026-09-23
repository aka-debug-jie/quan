"""Independently rebuild one registered closure run in a separate artifact root."""

from __future__ import annotations

import json
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Annotated

import typer

from quant_stack.research_json import canonical_json
from quant_stack.snapshot import write_immutable
from quant_stack_v3.closure_cli import CONTROL_ID, _control_spec, _runtime_spec
from quant_stack_v3.protocol import load_protocol
from quant_stack_v3.upgrade_cli import _validate_inputs
from quant_stack_v3.upgrade_parallel import run_upgrade_registry_parallel
from quant_stack_v3.upgrade_protocol import expand_experiment_registry, load_upgrade_protocol
from quant_stack_v3.upgrade_runner import UpgradeInputs, UpgradeRunSpec

app = typer.Typer(help="Deterministic, no-cache historical rebuild only.")


@app.command("run")
def run(
    experiment_id: Annotated[str, typer.Option()],
    source_matrix: Annotated[Path, typer.Option()],
    source_artifacts: Annotated[Path, typer.Option()],
    rebuild_artifacts: Annotated[Path, typer.Option()],
    bundle_root: Annotated[Path, typer.Option()],
    bars_path: Annotated[Path, typer.Option()],
    scores_path: Annotated[Path, typer.Option()],
    evidence_root: Annotated[Path, typer.Option()],
    action_evidence: Annotated[Path, typer.Option()],
    closure_protocol: Annotated[Path, typer.Option()] = Path(
        "configs/closure/cn_research_closure_next_v1.yaml"
    ),
) -> None:
    """Recompute one frozen run and verify every persisted canonical component."""
    if rebuild_artifacts.resolve() == source_artifacts.resolve():
        raise ValueError("rebuild must use a separate artifact root")
    if rebuild_artifacts.exists() and any(rebuild_artifacts.iterdir()):
        raise ValueError("no-cache rebuild requires a new empty artifact root")
    matrix = _mapping(json.loads(source_matrix.read_text(encoding="utf-8")))
    if matrix.get("closure_protocol_sha256") != _file_sha256(closure_protocol):
        raise ValueError("rebuild closure protocol differs from registered matrix")
    if matrix.get("action_evidence_sha256") != _file_sha256(action_evidence):
        raise ValueError("rebuild action evidence differs from registered matrix")
    identities = _mapping(matrix["result_identities"])
    source_identity = str(identities[experiment_id])
    old_result = source_artifacts / "runs" / source_identity / "result.json"
    source = _mapping(json.loads(old_result.read_text(encoding="utf-8")))
    if source.get("run_identity") != source_identity:
        raise ValueError("source result identity differs from registered matrix")
    experiment = _mapping(_mapping(source["identities"])["experiment"])
    if experiment.get("experiment_id") != experiment_id:
        raise ValueError("source experiment differs from requested registration")
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
    spec = UpgradeRunSpec(
        experiment_id=str(experiment["experiment_id"]),
        strategy_id=str(experiment["strategy_id"]),
        scenario_id=str(experiment["scenario_id"]),
        initial_cash=Decimal(str(experiment["initial_cash"])),
        execution_delay_sessions=int(str(experiment["execution_delay_sessions"])),
        cost_mode=str(experiment["cost_mode"]),
    )
    scale_candidates = matrix.get("scale_candidates", [])
    if not isinstance(scale_candidates, list | tuple):
        raise ValueError("rebuild scale selection is invalid")
    registered = {
        item.experiment_id: _runtime_spec(item)
        for item in expand_experiment_registry(
            upgrade, tuple(str(value) for value in scale_candidates)
        )
    }
    registered.update(
        {
            f"{CONTROL_ID}__{scenario.id}": _control_spec(scenario)
            for scenario in upgrade.core_scenarios
        }
    )
    if registered.get(experiment_id) != spec:
        raise ValueError("rebuild experiment differs from frozen registered specification")
    inputs = UpgradeInputs(
        bundle_root=bundle_root,
        bundle_sha256=upgrade.data.bundle_sha256,
        bars_path=bars_path,
        scores_path=scores_path,
        artifact_root=rebuild_artifacts,
        base_protocol_path=base_path,
        protocol_path=upgrade_path,
        action_overrides_path=action_evidence,
        action_evidence_root=evidence_root,
        closure_protocol_path=closure_protocol,
    )
    fresh = run_upgrade_registry_parallel(base, (spec,), inputs, maximum_workers=1)
    rebuilt_identity = str(fresh[experiment_id]["run_identity"])
    rebuilt_result = rebuild_artifacts / "runs" / rebuilt_identity / "result.json"
    report = verify_rebuild(old_result, rebuilt_result)
    encoded = canonical_json(report) + b"\n"
    path = rebuild_artifacts / "rebuild" / f"{sha256(encoded).hexdigest()}.json"
    write_immutable(path, encoded)
    typer.echo(json.dumps({"report": path.as_posix(), **report}, indent=2))


def verify_rebuild(source_result: Path, rebuilt_result: Path) -> dict[str, object]:
    """Require byte-identical results, NAV, ledger, intents and turnover outputs."""
    source = _mapping(json.loads(source_result.read_text(encoding="utf-8")))
    rebuilt = _mapping(json.loads(rebuilt_result.read_text(encoding="utf-8")))
    if source.get("run_identity") != rebuilt.get("run_identity") or source != rebuilt:
        raise ValueError("rebuilt run content differs from the registered result")
    files: dict[str, str] = {}
    for filename in (
        "result.json",
        "nav.parquet",
        "ledger.parquet",
        "order_intents.parquet",
        "daily_turnover.parquet",
    ):
        left = source_result.parent / filename
        right = rebuilt_result.parent / filename
        if left.is_file() != right.is_file():
            raise ValueError(f"rebuilt {filename} presence differs")
        if left.is_file():
            digest = _file_sha256(left)
            if digest != _file_sha256(right):
                raise ValueError(f"rebuilt {filename} content differs")
            files[filename] = digest
    return {
        "schema_version": 1,
        "status": "INDEPENDENT_NO_CACHE_REBUILD_PASS",
        "run_identity": source["run_identity"],
        "verified_files": files,
    }


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("rebuild field must be a mapping")
    return value


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    app()
