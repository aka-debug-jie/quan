"""Compare retained and evidence-repaired results without overwriting either."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Annotated

import typer

from quant_stack.research_json import canonical_json
from quant_stack.snapshot import write_immutable

app = typer.Typer(help="Publish old-to-new closure status and metric transitions.")
METRICS = (
    "total_return",
    "cagr",
    "annualized_volatility",
    "sharpe_ratio",
    "maximum_drawdown",
    "turnover",
    "total_transaction_costs",
)


@app.command("build")
def build(
    old_matrix: Annotated[Path, typer.Option()],
    old_artifacts: Annotated[Path, typer.Option()],
    new_matrix: Annotated[Path, typer.Option()],
    new_artifacts: Annotated[Path, typer.Option()],
    output_root: Annotated[Path, typer.Option()],
) -> None:
    """Write a content-addressed comparison of exactly the inherited 51 runs."""
    prior = _mapping(json.loads(old_matrix.read_text(encoding="utf-8")))
    revised = _mapping(json.loads(new_matrix.read_text(encoding="utf-8")))
    old_ids = _mapping(prior["result_identities"])
    new_ids = _mapping(revised["result_identities"])
    lineage = _mapping(revised["lineage"])
    rows: dict[str, object] = {}
    counts: dict[str, int] = {}
    for experiment_id, old_identity in sorted(old_ids.items()):
        entry = _mapping(lineage[experiment_id])
        if (
            entry["revision_of"] != old_identity
            or entry["new_run_identity"] != new_ids[experiment_id]
        ):
            raise ValueError("revision lineage does not bind the retained run")
        old_result = _result(old_artifacts, str(old_identity))
        new_result = _result(new_artifacts, str(new_ids[experiment_id]))
        old_valid = _valid(old_result)
        new_valid = _valid(new_result)
        transition = (
            ("VALID" if old_valid else "NOT_EVALUABLE")
            + "_TO_"
            + ("VALID" if new_valid else "NOT_EVALUABLE")
        )
        counts[transition] = counts.get(transition, 0) + 1
        row: dict[str, object] = {
            "old_run_identity": old_identity,
            "new_run_identity": new_ids[experiment_id],
            "transition": transition,
            "revision_kind": entry.get("kind", "UNSPECIFIED_REVISION"),
            "old_failure": None if old_valid else old_result.get("failure"),
            "new_failure": None if new_valid else new_result.get("failure"),
            "metric_deltas": None,
        }
        if old_valid and new_valid:
            old_metrics = _mapping(old_result["metrics"])
            new_metrics = _mapping(new_result["metrics"])
            row["metric_deltas"] = {
                key: float(str(new_metrics[key])) - float(str(old_metrics[key]))
                for key in METRICS
                if key in old_metrics and key in new_metrics
            }
        rows[str(experiment_id)] = row
    report = {
        "schema_version": 1,
        "status": "EVIDENCE_AND_ENGINEERING_REVISION_COMPARISON_COMPLETE",
        "old_matrix_sha256": _file_sha256(old_matrix),
        "new_matrix_sha256": _file_sha256(new_matrix),
        "inherited_run_count": len(old_ids),
        "new_only_run_count": len(new_ids) - len(old_ids),
        "transition_counts": counts,
        "runs": rows,
        "interpretation": [
            "invalid to valid has no fabricated old metric delta",
            "metric differences between two valid runs mix factual and execution-order correction",
            "new diagnostic controls are not renamed inherited candidates",
        ],
    }
    encoded = canonical_json(report) + b"\n"
    path = output_root / "revision_delta" / f"{sha256(encoded).hexdigest()}.json"
    write_immutable(path, encoded)
    typer.echo(
        json.dumps(
            {
                "report": path.as_posix(),
                "counts": counts,
                "new_only_runs": len(new_ids) - len(old_ids),
            },
            indent=2,
        )
    )


def _result(artifacts: Path, identity: str) -> dict[str, object]:
    return _mapping(json.loads((artifacts / "runs" / identity / "result.json").read_text()))


def _valid(result: dict[str, object]) -> bool:
    return str(result.get("RESEARCH_VALIDITY", "")).startswith("VALID_")


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("revision field must be a mapping")
    return value


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    app()
