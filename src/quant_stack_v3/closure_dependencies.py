"""Map retained run failures to shared benchmark and candidate dependencies."""

from __future__ import annotations

import json
import re
from hashlib import sha256
from pathlib import Path
from typing import Annotated

import typer

from quant_stack.research_json import canonical_json
from quant_stack.snapshot import write_immutable
from quant_stack_v3.upgrade_statistics import BENCHMARKS

app = typer.Typer(help="Read-only diagnosis of the retained upgrade matrix.")
_ACTION = re.compile(r"held position has unexplained action on (\d{4}-\d{2}-\d{2}): (.+)")
_VALUATION = re.compile(r"unexplained held valuation missing on (\d{4}-\d{2}-\d{2}): (.+)")


@app.command("build")
def build(
    matrix_path: Annotated[Path, typer.Option()],
    artifact_root: Annotated[Path, typer.Option()],
    output_root: Annotated[Path, typer.Option()],
) -> None:
    """Publish a content-addressed event-to-comparison dependency graph."""
    matrix = _mapping(json.loads(matrix_path.read_text(encoding="utf-8")))
    identities = _mapping(matrix["result_identities"])
    rows: dict[tuple[str, str, str], dict[str, object]] = {}
    statuses: dict[str, str] = {}
    for experiment_id, identity in sorted(identities.items()):
        result_path = artifact_root / "runs" / str(identity) / "result.json"
        result = _mapping(json.loads(result_path.read_text(encoding="utf-8")))
        status = str(result.get("RESEARCH_VALIDITY", "UNKNOWN"))
        statuses[str(experiment_id)] = status
        if status.startswith("VALID_"):
            continue
        failure = str(result.get("failure", ""))
        parsed = _parse_failure(failure)
        if parsed is None:
            continue
        date_value, symbols, kind = parsed
        for symbol in symbols:
            key = (symbol, date_value, kind)
            row = rows.setdefault(
                key,
                {
                    "symbol": symbol,
                    "session": date_value,
                    "gap_kind": kind,
                    "direct_runs": [],
                    "direct_strategies": [],
                    "dependent_comparisons": [],
                },
            )
            _list(row, "direct_runs").append(str(experiment_id))
            _list(row, "direct_strategies").append(str(result["strategy_id"]))
    for row in rows.values():
        direct = set(_list(row, "direct_strategies"))
        comparisons = {
            candidate
            for candidate, benchmark in BENCHMARKS.items()
            if benchmark in direct or candidate in direct
        }
        row["direct_runs"] = sorted(set(_list(row, "direct_runs")))
        row["direct_strategies"] = sorted(direct)
        row["dependent_comparisons"] = sorted(comparisons)
        row["direct_run_count"] = len(_list(row, "direct_runs"))
        row["comparison_count"] = len(comparisons)
    report = {
        "schema_version": 1,
        "status": "RETAINED_BLOCKING_DEPENDENCY_MAP",
        "matrix_sha256": _file_sha256(matrix_path),
        "registered_runs": len(identities),
        "valid_runs": sum(value.startswith("VALID_") for value in statuses.values()),
        "not_evaluable_runs": sum(not value.startswith("VALID_") for value in statuses.values()),
        "events": [rows[key] for key in sorted(rows)],
    }
    encoded = canonical_json(report) + b"\n"
    path = output_root / "dependency" / f"{sha256(encoded).hexdigest()}.json"
    write_immutable(path, encoded)
    typer.echo(json.dumps({"report": path.as_posix(), **report}, indent=2))


def _parse_failure(failure: str) -> tuple[str, tuple[str, ...], str] | None:
    for pattern, kind in ((_ACTION, "unexplained_action"), (_VALUATION, "missing_valuation")):
        matched = pattern.search(failure)
        if matched is not None:
            symbols = tuple(item.strip() for item in matched.group(2).split(","))
            return matched.group(1), symbols, kind
    return None


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("dependency record must be a mapping")
    return value


def _list(value: dict[str, object], field: str) -> list[str]:
    candidate = value[field]
    if not isinstance(candidate, list):
        raise ValueError("dependency field must be a list")
    return candidate


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    app()
