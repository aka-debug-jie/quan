"""Minimal synthetic CSI300 development projection with explicit dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

from quant_stack_v2.dev_contract import (
    DevContract,
    DevEvidence,
    Digest,
    Member,
    Row,
    StrictModel,
    UsePins,
    canonical,
    digest,
    load_evidence,
    load_source,
    read_blob,
    write_blob,
)


class ViewData(StrictModel):
    """Only approved symbols, fields and required calendar dependency rows."""

    schema_version: Literal[1]
    rows: tuple[Row, ...]
    members: tuple[Member, ...]


class ViewManifest(StrictModel):
    """Non-promoting development view tied to one verified use and evidence file."""

    schema_version: Literal[1]
    status: Literal["LIMITED_DEV_RESEARCH"]
    data_kind: Literal["SYNTHETIC"]
    universe: Literal["csi300"]
    contract_sha256: Digest
    evidence_sha256: Digest
    source_sha256: Digest
    exporter_version: Literal["limited-dev-export-v1"]
    data_sha256: Digest
    row_count: int


@dataclass(frozen=True)
class VerifiedView:
    """Verified input returned by the fixed view loader; not formal research authority."""

    contract: DevContract
    evidence: DevEvidence
    data: ViewData
    contract_sha256: str
    evidence_sha256: str
    view_sha256: str


def sample_sessions(contract: DevContract) -> tuple[date, ...]:
    """Formal train/validation dates; warm-up/label tails cannot become samples."""
    return tuple(
        d
        for d in contract.sessions
        if contract.train.start <= d <= contract.train.end
        or contract.valid.start <= d <= contract.valid.end
    )


def dependency_sessions(contract: DevContract) -> tuple[date, ...]:
    """Compute exactly required causal and label endpoints independently of missing values."""
    positions: set[int] = set()
    for d in sample_sessions(contract):
        i = contract.sessions.index(d)
        positions.add(i)
        positions.update(i - f.lag for f in contract.features)
        positions.update((i + contract.label.start_offset, i + contract.label.end_offset))
    if min(positions) < 0 or max(positions) >= len(contract.sessions):
        raise ValueError("dependency exceeds approved source boundary")
    return tuple(contract.sessions[i] for i in sorted(positions))


def _check_payload(data: ViewData, contract: DevContract) -> None:
    expected = dependency_keys(contract, data.members)
    actual = {(r.symbol, r.session) for r in data.rows}
    if len(actual) != len(data.rows) or actual != expected:
        raise ValueError("view symbol/date dependency scope mismatch")
    if any(set(r.values) != set(contract.fields) for r in data.rows):
        raise ValueError("view field allowlist mismatch")
    if any(
        m.symbol not in contract.symbols
        or not contract.source.start <= m.start <= m.end <= contract.source.end
        for m in data.members
    ):
        raise ValueError("view membership scope mismatch")


def dependency_keys(contract: DevContract, members: tuple[Member, ...]) -> set[tuple[str, date]]:
    """Project dependencies only for membership at each formal T, never at T+h."""
    keys: set[tuple[str, date]] = set()
    for symbol in contract.symbols:
        for day in sample_sessions(contract):
            if not any(m.symbol == symbol and m.start <= day <= m.end for m in members):
                continue
            i = contract.sessions.index(day)
            indices = {i, i + contract.label.start_offset, i + contract.label.end_offset}
            indices.update(i - f.lag for f in contract.features)
            if min(indices) < 0 or max(indices) >= len(contract.sessions):
                raise ValueError("dependency exceeds approved source boundary")
            keys.update((symbol, contract.sessions[j]) for j in indices)
    return keys


def export_view(source_root: Path, authority: Path, view_root: Path, pins: UsePins) -> str:
    """Project only approved synthetic rows after reopening all bound source evidence."""
    contract, evidence = load_evidence(authority, pins)
    source = load_source(source_root, contract)
    if (
        evidence.membership_sha256 != digest([m.model_dump(mode="json") for m in source.members])
        or evidence.source_rows != len(source.rows)
        or evidence.provider_id != source.provider_id
    ):
        raise ValueError("source evidence payload mismatch")
    source_rows = {(r.symbol, r.session): r for r in source.rows}
    rows = []
    for symbol, day in sorted(dependency_keys(contract, source.members)):
        row = source_rows.get((symbol, day))
        values = {f: row.values[f] if row is not None else None for f in contract.fields}
        rows.append(Row(symbol=symbol, session=day, values=values))
    members = tuple(
        Member(
            symbol=m.symbol,
            start=max(m.start, contract.source.start),
            end=min(m.end, contract.source.end),
        )
        for m in source.members
        if m.symbol in contract.symbols
        and m.start <= contract.source.end
        and m.end >= contract.source.start
    )
    data = ViewData(schema_version=1, rows=tuple(rows), members=members)
    _check_payload(data, contract)
    data_sha = write_blob(view_root, canonical(data))
    manifest = ViewManifest(
        schema_version=1,
        status="LIMITED_DEV_RESEARCH",
        data_kind="SYNTHETIC",
        universe="csi300",
        contract_sha256=pins.contract_sha256,
        evidence_sha256=pins.evidence_sha256,
        source_sha256=contract.source_sha256,
        exporter_version="limited-dev-export-v1",
        data_sha256=data_sha,
        row_count=len(rows),
    )
    return write_blob(view_root, canonical(manifest))


def load_view(authority: Path, view_root: Path, pins: UsePins, view_sha256: str) -> VerifiedView:
    """Reload actual hash-bound view and use files before every run or reuse."""
    if pins.view_sha256 is None or pins.view_sha256 != view_sha256:
        raise ValueError("view differs from operator-approved identity")
    contract, evidence = load_evidence(authority, pins)
    manifest = ViewManifest.model_validate_json(read_blob(view_root, view_sha256))
    if (
        manifest.contract_sha256 != pins.contract_sha256
        or manifest.evidence_sha256 != pins.evidence_sha256
        or manifest.source_sha256 != contract.source_sha256
    ):
        raise ValueError("view/use identity mismatch")
    data = ViewData.model_validate_json(read_blob(view_root, manifest.data_sha256))
    if manifest.row_count != len(data.rows):
        raise ValueError("view row count mismatch")
    _check_payload(data, contract)
    return VerifiedView(
        contract, evidence, data, pins.contract_sha256, pins.evidence_sha256, view_sha256
    )
