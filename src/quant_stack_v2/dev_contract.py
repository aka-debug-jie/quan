"""Versioned limited-use evidence; no formal qualification or sealed authority."""

from __future__ import annotations

import ctypes
import json
import math
import os
import re
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from itertools import pairwise
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Name = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,63}$")]
VALIDATOR_VERSION: Literal["limited-dev-evidence-v1"] = "limited-dev-evidence-v1"


class StrictModel(BaseModel):
    """Reject undeclared fields, including caller-supplied qualification decisions."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False, strict=True)


class Span(StrictModel):
    """Inclusive session-date interval."""

    start: date
    end: date

    @model_validator(mode="after")
    def ordered(self) -> Span:
        if self.start > self.end:
            raise ValueError("reversed date interval")
        return self


class FeatureSpec(StrictModel):
    """A named causal lag of an explicitly allowed normalized field."""

    name: Name
    field: Name
    lag: Annotated[int, Field(ge=0, le=256)]


class LabelSpec(StrictModel):
    """Exact endpoint ratio in exchange sessions, not calendar-day offsets."""

    kind: Literal["forward_ratio"]
    field: Name
    start_offset: Annotated[int, Field(ge=1)]
    end_offset: Annotated[int, Field(ge=2)]

    @model_validator(mode="after")
    def ordered(self) -> LabelSpec:
        if self.end_offset <= self.start_offset:
            raise ValueError("label end must follow label start")
        return self


class ModelSpec(StrictModel):
    """One fully specified, fixed smoke model; no parameter search interface."""

    kind: Literal["linear", "lightgbm"]
    seed: Annotated[int, Field(ge=0)]
    params: dict[str, bool | int | float]

    @model_validator(mode="after")
    def fixed_parameters(self) -> ModelSpec:
        expected = (
            {"fit_intercept"}
            if self.kind == "linear"
            else {"n_estimators", "num_leaves", "learning_rate", "min_child_samples", "max_depth"}
        )
        if set(self.params) != expected:
            raise ValueError("complete explicit model parameters required")
        if self.kind == "linear":
            if type(self.params["fit_intercept"]) is not bool:
                raise ValueError("fit_intercept must be boolean")
        else:
            for key in expected - {"learning_rate"}:
                if type(self.params[key]) is not int or self.params[key] <= 0:
                    raise ValueError("positive integer tree parameters required")
            if (
                type(self.params["learning_rate"]) is bool
                or not 0 < self.params["learning_rate"] <= 1
            ):
                raise ValueError("invalid learning rate")
        return self


class DevContract(StrictModel):
    """Executable synthetic contract; missing real specifications cannot default in."""

    schema_version: Literal[1]
    usage: Literal["LIMITED_DEV_RESEARCH"]
    run_kind: Literal["DEV_SMOKE"]
    data_kind: Literal["SYNTHETIC"]
    universe: Literal["csi300"]
    formal_qualification: Literal["BLOCKED_DATA"]
    sealed_test: Literal["NOT_STARTED"]
    snapshot_sha256: Digest
    tree_sha256: Digest
    source_sha256: Digest
    price_semantics: Literal["SYNTHETIC_POSITIVE_LEVELS"]
    symbols: tuple[Name, ...]
    fields: tuple[Name, ...]
    sessions: tuple[date, ...]
    source: Span
    train: Span
    valid: Span
    warmup_sessions: Annotated[int, Field(ge=0)]
    train_label_end: date
    valid_label_end: date
    embargo_sessions: Annotated[int, Field(ge=0)]
    features: tuple[FeatureSpec, ...]
    label: LabelSpec
    preprocessing: Literal["train_standardize_complete_cases"]
    models: tuple[ModelSpec, ...]

    @model_validator(mode="after")
    def scope_is_exact(self) -> DevContract:
        if not self.symbols or len(set(self.symbols)) != len(self.symbols):
            raise ValueError("unique explicit symbols required")
        if any(not s.startswith("SYNTH_") for s in self.symbols):
            raise ValueError("real market adapter/authorization is not implemented")
        if not self.fields or len(set(self.fields)) != len(self.fields):
            raise ValueError("unique fields required")
        if not self.sessions or tuple(sorted(set(self.sessions))) != self.sessions:
            raise ValueError("ordered unique approved calendar required")
        boundaries = [
            self.source.start,
            self.source.end,
            self.train.start,
            self.train.end,
            self.valid.start,
            self.valid.end,
            self.train_label_end,
            self.valid_label_end,
        ]
        if any(d not in self.sessions for d in boundaries):
            raise ValueError("all boundaries must be actual approved sessions")
        if (self.sessions[0], self.sessions[-1]) != (self.source.start, self.source.end):
            raise ValueError("calendar outside source scope")
        if (
            not self.source.start
            <= self.train.start
            <= self.train.end
            < self.valid.start
            <= self.valid.end
            <= self.source.end
        ):
            raise ValueError("train/validation ordering or scope mismatch")
        if not self.features or len({f.name for f in self.features}) != len(self.features):
            raise ValueError("unique features required")
        if set(f.field for f in self.features) | {self.label.field} != set(self.fields):
            raise ValueError("field allowlist must exactly match feature/label dependencies")
        if self.warmup_sessions != max(f.lag for f in self.features):
            raise ValueError("warm-up must match actual feature lookback")
        if self.sessions.index(self.train.start) < self.warmup_sessions:
            raise ValueError("insufficient feature warm-up")
        for span, boundary in [
            (self.train, self.train_label_end),
            (self.valid, self.valid_label_end),
        ]:
            last = self.sessions.index(span.end) + self.label.end_offset
            if last >= len(self.sessions) or self.sessions[last] > boundary:
                raise ValueError("label crosses forbidden dependency boundary")
        if (
            self.sessions.index(self.valid.start) - self.sessions.index(self.train_label_end)
            <= self.embargo_sessions
        ):
            raise ValueError("training label dependencies violate validation embargo")
        if not self.models or len({m.kind for m in self.models}) != len(self.models):
            raise ValueError("unique fixed models required")
        if len({m.seed for m in self.models}) != 1:
            raise ValueError("DEV_SMOKE must bind a single seed")
        return self


class Member(StrictModel):
    """Membership at T; future missing labels never decide membership."""

    symbol: Name
    start: date
    end: date


class Row(StrictModel):
    """One normalized source observation; missing data remain explicit nulls."""

    symbol: Name
    session: date
    values: dict[str, float | None]


class SourcePacket(StrictModel):
    """Small normalized synthetic source, not an arbitrary Qlib or sealed reader."""

    schema_version: Literal[1]
    data_kind: Literal["SYNTHETIC"]
    universe: Literal["csi300"]
    provider_id: Name
    price_semantics: Literal["SYNTHETIC_POSITIVE_LEVELS"]
    sessions: tuple[date, ...]
    fields: tuple[Name, ...]
    members: tuple[Member, ...]
    rows: tuple[Row, ...]


class DevEvidence(StrictModel):
    """Provider-neutral, pinned evidence about actual normalized source bytes."""

    schema_version: Literal[1]
    kind: Literal["independent_source_scope_verification"]
    validator_version: Literal["limited-dev-evidence-v1"]
    contract_sha256: Digest
    snapshot_sha256: Digest
    tree_sha256: Digest
    source_sha256: Digest
    universe: Literal["csi300"]
    symbols: tuple[Name, ...]
    fields: tuple[Name, ...]
    source: Span
    provider_id: Name
    calendar_sha256: Digest
    membership_sha256: Digest
    source_rows: Annotated[int, Field(ge=0)]


@dataclass(frozen=True)
class UsePins:
    """Operator/test-owned trust pins, never a caller-supplied QUALIFIED string."""

    contract_sha256: str
    evidence_sha256: str
    view_sha256: str | None = None


def canonical(value: Any) -> bytes:
    """Encode stable JSON without nonfinite placeholder values."""
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"
    )


def digest(value: Any) -> str:
    """Identity of canonical schema data."""
    return sha256(canonical(value)).hexdigest()


def tree_identity(source_sha256: str) -> str:
    """Identity of this normalized synthetic tree, not the original Qlib archive."""
    return digest({"source.json": source_sha256})


@contextmanager
def directory(root: Path, *, create: bool = False) -> Iterator[int]:
    """Walk directory descriptors without following symlinks or entering sealed roots."""
    absolute = Path(os.path.abspath(root))
    if (
        absolute == Path("/")
        or ".." in root.parts
        or str(absolute).startswith("/srv/quant-v2/sealed_holdout")
    ):
        raise ValueError("forbidden root or path traversal")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in absolute.parts[1:]:
            if create:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


def read_blob(root: Path, identity: str, suffix: str = ".json") -> bytes:
    """Read one regular hash-named blob, refusing links and mismatched bytes."""
    if re.fullmatch(r"[a-f0-9]{64}", identity) is None or suffix not in (".json", ".bin"):
        raise ValueError("invalid content identity")
    with directory(root) as fd:
        handle = os.open(identity + suffix, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        with os.fdopen(handle, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or info.st_size > 64 * 1024 * 1024
            ):
                raise ValueError("blob must be a bounded unlinked regular file")
            body = stream.read(64 * 1024 * 1024 + 1)
            if len(body) > 64 * 1024 * 1024:
                raise ValueError("blob exceeds bounded size")
    if sha256(body).hexdigest() != identity:
        raise ValueError("evidence/blob SHA-256 mismatch")
    return body


def write_blob(root: Path, body: bytes, suffix: str = ".json") -> str:
    """Publish complete immutable bytes atomically; interrupted writes never look complete."""
    if suffix not in (".json", ".bin"):
        raise ValueError("unsupported artifact suffix")
    if len(body) > 64 * 1024 * 1024:
        raise ValueError("blob exceeds bounded size")
    identity = sha256(body).hexdigest()
    with directory(root, create=True) as fd:
        temporary = ".stage-" + uuid4().hex
        handle = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd
        )
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                _publish_no_replace(fd, temporary, identity + suffix)
            except FileExistsError:
                if read_blob(root, identity, suffix) != body:
                    raise ValueError("immutable artifact collision") from None
            os.fsync(fd)
        finally:
            try:
                os.unlink(temporary, dir_fd=fd)
            except FileNotFoundError:
                pass
    return identity


def _publish_no_replace(fd: int, temporary: str, target: str) -> None:
    """Linux atomic no-replace rename avoids a crash window with two hardlinks."""
    library = ctypes.CDLL(None, use_errno=True)
    rename = library.renameat2
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(fd, temporary.encode(), fd, target.encode(), 1) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), target)


def load_contract(root: Path, identity: str) -> DevContract:
    """Open and validate the exact approved-use schema, not a status object."""
    return DevContract.model_validate_json(read_blob(root, identity))


def load_evidence(root: Path, pins: UsePins) -> tuple[DevContract, DevEvidence]:
    """Check actual evidence bytes, schema, validator and identical complete use scope."""
    contract = load_contract(root, pins.contract_sha256)
    evidence = DevEvidence.model_validate_json(read_blob(root, pins.evidence_sha256))
    if evidence.contract_sha256 != pins.contract_sha256:
        raise ValueError("cross-contract evidence")
    for field in (
        "snapshot_sha256",
        "tree_sha256",
        "source_sha256",
        "universe",
        "symbols",
        "fields",
        "source",
    ):
        if getattr(evidence, field) != getattr(contract, field):
            raise ValueError("evidence source/scope mismatch: " + field)
    if evidence.calendar_sha256 != digest([d.isoformat() for d in contract.sessions]):
        raise ValueError("calendar evidence mismatch")
    return contract, evidence


def load_source(root: Path, contract: DevContract) -> SourcePacket:
    """Validate source identity and actual rows before creating any view."""
    source = SourcePacket.model_validate_json(read_blob(root, contract.source_sha256))
    if contract.snapshot_sha256 != contract.source_sha256 or contract.tree_sha256 != tree_identity(
        contract.source_sha256
    ):
        raise ValueError("synthetic snapshot/tree identity mismatch")
    if source.sessions != contract.sessions or source.price_semantics != contract.price_semantics:
        raise ValueError("source calendar/price semantics mismatch")
    if not set(contract.fields) <= set(source.fields):
        raise ValueError("source lacks declared fields")
    seen: set[tuple[str, date]] = set()
    for row in source.rows:
        key = (row.symbol, row.session)
        if (
            key in seen
            or row.session not in source.sessions
            or set(row.values) != set(source.fields)
        ):
            raise ValueError("source row identity/schema mismatch")
        if any(v is not None and not math.isfinite(v) for v in row.values.values()):
            raise ValueError("nonfinite source value")
        seen.add(key)
    for m in source.members:
        if m.start > m.end:
            raise ValueError("invalid membership interval")
    for symbol in {m.symbol for m in source.members}:
        intervals = sorted((m.start, m.end) for m in source.members if m.symbol == symbol)
        if any(a[1] >= b[0] for a, b in pairwise(intervals)):
            raise ValueError("overlapping membership intervals")
    for row in source.rows:
        value = row.values[contract.label.field]
        if value is not None and value <= 0:
            raise ValueError("positive label price levels required")
    if not set(contract.symbols) <= {m.symbol for m in source.members}:
        raise ValueError("source membership does not cover approved symbols")
    return source


def attest_synthetic(source_root: Path, authority: Path, contract_sha256: str) -> str:
    """Produce provider-neutral source verification only after reopening actual data."""
    contract = load_contract(authority, contract_sha256)
    source = load_source(source_root, contract)
    evidence = DevEvidence(
        schema_version=1,
        kind="independent_source_scope_verification",
        validator_version=VALIDATOR_VERSION,
        contract_sha256=contract_sha256,
        snapshot_sha256=contract.snapshot_sha256,
        tree_sha256=contract.tree_sha256,
        source_sha256=contract.source_sha256,
        universe=contract.universe,
        symbols=contract.symbols,
        fields=contract.fields,
        source=contract.source,
        provider_id=source.provider_id,
        calendar_sha256=digest([d.isoformat() for d in source.sessions]),
        membership_sha256=digest([m.model_dump(mode="json") for m in source.members]),
        source_rows=len(source.rows),
    )
    return write_blob(authority, canonical(evidence))
