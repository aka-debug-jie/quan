"""Publish safe issuer-evidence links for one completed closure matrix."""

from __future__ import annotations

import json
import subprocess
from datetime import date
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Annotated

import pandas as pd
import typer
import yaml

from quant_stack.research_json import canonical_json
from quant_stack.snapshot import write_immutable
from quant_stack_v3.actions import load_no_participation_overrides

app = typer.Typer(help="Publish bounded source metadata without raw prices or holdings.")


def verify_inherited_evidence_archive(action_path: Path, evidence_root: Path) -> int:
    """Check archived bytes for every inherited schema-1 issuer document."""
    checked = 0
    for layer in _evidence_layers(action_path):
        for value in _sequence(layer["events"]):
            event = _mapping(value)
            if "source_sha256" not in event:
                continue
            digest = str(event["source_sha256"])
            source_path = evidence_root / "raw" / f"{digest}.pdf"
            if not source_path.is_file() or _file_sha256(source_path) != digest:
                raise ValueError("inherited issuer evidence bytes differ")
            checked += 1
    return checked


@app.command("publish")
def publish(
    matrix_path: Annotated[Path, typer.Option()],
    manifest_path: Annotated[Path, typer.Option()],
    action_evidence_path: Annotated[Path, typer.Option()],
    evidence_root: Annotated[Path, typer.Option()],
    artifact_root: Annotated[Path, typer.Option()],
    validated_code_commit: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Bind verified filings and run lineage to a Console-compatible manifest."""
    load_no_participation_overrides(action_evidence_path, evidence_root=evidence_root)
    verify_inherited_evidence_archive(action_evidence_path, evidence_root)
    matrix = _mapping(json.loads(matrix_path.read_text(encoding="utf-8")))
    manifest = _mapping(json.loads(manifest_path.read_text(encoding="utf-8")))
    if manifest.get("matrix_sha256") != _file_sha256(matrix_path):
        raise ValueError("closure publication manifest and matrix differ")
    layers = _evidence_layers(action_evidence_path)
    records: dict[str, dict[str, object]] = {}
    event_ids: dict[tuple[str, date], list[str]] = {}
    for item in (event for layer in layers for event in _sequence(layer["events"])):
        event = _mapping(item)
        symbol = str(event["symbol"])
        effective = date.fromisoformat(str(event["effective_date"]))
        event_ids.setdefault((symbol, effective), [])
        documents = event.get("source_documents")
        if documents is None:
            documents = [
                {
                    "sha256": event["source_sha256"],
                    "url": event["source_url"],
                    "pages": [],
                    "published_on": None,
                    "retrieved_at_utc": None,
                    "source_kind": "legacy_issuer_filing",
                }
            ]
        for document in _sequence(documents):
            source = _mapping(document)
            digest = str(source["sha256"])
            source_path = evidence_root / "raw" / f"{digest}.pdf"
            if not source_path.is_file() or _file_sha256(source_path) != digest:
                raise ValueError("inherited or new issuer evidence bytes differ")
            evidence_id = f"evidence:closure:{symbol}:{effective}:{digest[:12]}"
            records[evidence_id] = {
                "source_kind": str(source.get("source_kind", "issuer_filing")),
                "sha256": digest,
                "source_url": str(source["url"]),
                "pages": source["pages"],
                "published_on": source["published_on"],
                "retrieved_at_utc": source["retrieved_at_utc"],
                "data_use_level": manifest["DATA_USE_LEVEL"],
                "limitations": ["retrospective accounting verification only"],
            }
            event_ids[(symbol, effective)].append(evidence_id)
    for item in (
        event for layer in layers for event in _sequence(layer.get("unresolved_events", []))
    ):
        event = _mapping(item)
        symbol = str(event["symbol"])
        effective = date.fromisoformat(str(event["effective_date"]))
        digest = str(event["source_sha256"])
        source_path = evidence_root / "raw" / f"{digest}.pdf"
        if not source_path.is_file() or _file_sha256(source_path) != digest:
            raise ValueError("unresolved event evidence bytes differ")
        evidence_id = f"evidence:closure:{symbol}:{effective}:{digest[:12]}"
        records[evidence_id] = {
            "source_kind": "issuer_filing_unresolved_event",
            "sha256": digest,
            "source_url": str(event["source_url"]),
            "pages": event["source_pages"],
            "data_use_level": manifest["DATA_USE_LEVEL"],
            "limitations": [str(event["status"])],
        }
        event_ids[(symbol, effective)] = [evidence_id]
    identities = _mapping(matrix["result_identities"])
    run_evidence: dict[str, list[str]] = {}
    result_hashes: dict[str, str] = {}
    for _, identity in sorted(identities.items()):
        run_identity = str(identity)
        run_root = artifact_root / "runs" / run_identity
        result_path = run_root / "result.json"
        result_hashes[run_identity] = _file_sha256(result_path)
        result = _mapping(json.loads(result_path.read_text(encoding="utf-8")))
        matched: set[str] = set()
        ledger = run_root / "ledger.parquet"
        if ledger.is_file():
            frame = pd.read_parquet(ledger, columns=["event_type", "occurred_on", "payload"])
            snapshots = frame.loc[frame.event_type == "snapshot", ["occurred_on", "payload"]]
            for (symbol, effective), evidence_ids in event_ids.items():
                before = snapshots.loc[snapshots.occurred_on < effective.isoformat()]
                if before.empty:
                    continue
                state = _mapping(json.loads(str(before.iloc[-1].payload)))
                positions = _mapping(state["positions"])
                if Decimal(str(positions.get(symbol, 0))) > 0:
                    matched.update(evidence_ids)
        else:
            failure = str(result.get("failure", ""))
            for (symbol, effective), evidence_ids in event_ids.items():
                if symbol in failure and effective.isoformat() in failure:
                    matched.update(evidence_ids)
        run_evidence[run_identity] = sorted(matched)
    index = {"schema_version": 1, "records": records, "run_evidence": run_evidence}
    encoded = canonical_json(index) + b"\n"
    evidence_sha = sha256(encoded).hexdigest()
    evidence_path = artifact_root / "evidence" / f"{evidence_sha}.json"
    write_immutable(evidence_path, encoded)
    published = manifest | {
        "evidence_index_sha256": evidence_sha,
        "result_sha256s": result_hashes,
    }
    inherited_commit = published.pop("source_commit", None)
    if inherited_commit is not None:
        published["base_source_commit"] = inherited_commit
    outcomes = [str(value) for value in _mapping(matrix["candidate_outcomes"]).values()]
    if int(str(manifest["retained_candidates"])) > 0:
        published["ECONOMIC_OUTCOME"] = "RETAINED_FOR_NEXT_VALIDATION_REVIEW"
    elif "NOT_EVALUABLE" in outcomes:
        published["ECONOMIC_OUTCOME"] = "MIXED_EVALUABILITY_NO_RETAINED_CANDIDATE"
    elif "INCONCLUSIVE_HISTORICAL" in outcomes:
        published["ECONOMIC_OUTCOME"] = "INCONCLUSIVE_NO_RETAINED_CANDIDATE"
    else:
        published["ECONOMIC_OUTCOME"] = "NO_HISTORICAL_EDGE_NO_RETAINED_CANDIDATE"
    if validated_code_commit is not None:
        if len(validated_code_commit) != 40:
            raise ValueError("validated code commit must be a full SHA")
        source_root = Path(__file__).resolve().parents[2]
        actual_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=source_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=source_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if validated_code_commit != actual_commit or dirty:
            raise ValueError("validated code commit requires a matching clean worktree")
        published["validated_code_commit"] = validated_code_commit
        published["source_commit"] = validated_code_commit
    else:
        published["source_commit"] = "UNCOMMITTED_UNVALIDATED"
    manifest_bytes = canonical_json(published) + b"\n"
    published_path = artifact_root / "manifests" / f"{sha256(manifest_bytes).hexdigest()}.json"
    write_immutable(published_path, manifest_bytes)
    typer.echo(
        json.dumps(
            {
                "manifest": published_path.as_posix(),
                "evidence_index_sha256": evidence_sha,
                "source_records": len(records),
                "runs_with_applied_evidence": sum(bool(value) for value in run_evidence.values()),
            },
            indent=2,
        )
    )


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("closure publication field must be a mapping")
    return value


def _sequence(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("closure publication field must be a list")
    return value


def _evidence_layers(path: Path) -> list[dict[str, object]]:
    payload = _mapping(yaml.safe_load(path.read_text(encoding="utf-8")))
    inherited = payload.get("inherits")
    if not isinstance(inherited, dict):
        return [payload]
    inherited_path = (path.parent / str(inherited["path"])).resolve()
    if _file_sha256(inherited_path) != inherited.get("sha256"):
        raise ValueError("publication evidence inheritance hash differs")
    return [*_evidence_layers(inherited_path), payload]


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    app()
