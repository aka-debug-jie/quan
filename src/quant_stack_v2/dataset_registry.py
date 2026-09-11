"""Fail-closed external-dataset registry for the isolated Quant V2 research line."""

from __future__ import annotations

import json
import os
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Literal
from urllib.request import Request, urlopen

import yaml
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from quant_stack.snapshot import write_immutable


class DatasetRegistryError(ValueError):
    """Raised when V2 external data cannot satisfy its declared contract."""


class DatasetUsageLevel(StrEnum):
    """Maximum evidence use currently permitted for one dataset."""

    FIXTURE_ONLY = "FIXTURE_ONLY"
    RESEARCH_ADJUSTED_ONLY = "RESEARCH_ADJUSTED_ONLY"
    BACKTEST_RESEARCH = "BACKTEST_RESEARCH"
    EXECUTION_QUALIFIED = "EXECUTION_QUALIFIED"
    PROSPECTIVE = "PROSPECTIVE"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DatasetLicense(_StrictModel):
    """Separate repository code license from market-data redistribution rights."""

    code_license: str
    market_data_rights_reviewed: bool
    redistribution_permitted: bool
    notes: str


class DatasetArtifacts(_StrictModel):
    """Expected remote artifacts; hashes may remain absent only before qualification."""

    archive_url: HttpUrl | None = None
    archive_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    manifest_url: HttpUrl | None = None
    manifest_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    manifest_bindings: dict[str, str] = Field(default_factory=dict)


class DatasetCoverage(_StrictModel):
    """Observed coverage remains unset until an archived dataset is inspected."""

    market: str
    frequency: str
    first_date: date | None = None
    last_date: date | None = None

    @model_validator(mode="after")
    def ordered_dates(self) -> DatasetCoverage:
        if self.first_date and self.last_date and self.first_date > self.last_date:
            raise ValueError("dataset coverage dates are reversed")
        return self


class DatasetSemantics(_StrictModel):
    """Price, membership and corporate-action meanings required before research."""

    price_type: str
    raw_price_recoverable: bool
    adjustment_definition: str
    historical_membership: bool
    corporate_actions_officially_verified: bool


class DatasetRegistry(_StrictModel):
    """One immutable external-dataset declaration independent of V1 authorities."""

    schema_version: int = Field(ge=1)
    dataset_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    source_repository: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    source_release: str = Field(min_length=1)
    source_release_kind: Literal["github_release", "commit_snapshot"]
    retrieved_at_utc: datetime | None = None
    usage_level: DatasetUsageLevel
    qualification_status: Literal["METADATA_ONLY", "PENDING_CAPTURE_AND_INSPECTION", "QUALIFIED"]
    license: DatasetLicense
    artifacts: DatasetArtifacts
    coverage: DatasetCoverage
    semantics: DatasetSemantics
    allowed_uses: tuple[str, ...]
    forbidden_uses: tuple[str, ...]

    @property
    def identity_sha256(self) -> str:
        """Return the stable hash of the validated registry semantics."""
        encoded = json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode()
        return sha256(encoded).hexdigest()

    @model_validator(mode="after")
    def fail_closed_contract(self) -> DatasetRegistry:
        if self.retrieved_at_utc is not None and self.retrieved_at_utc.tzinfo is None:
            raise ValueError("dataset retrieval time must be timezone-aware")
        if not self.semantics.adjustment_definition.strip():
            raise ValueError("dataset adjustment semantics must be declared")
        if len(set(self.allowed_uses)) != len(self.allowed_uses) or len(
            set(self.forbidden_uses)
        ) != len(self.forbidden_uses):
            raise ValueError("dataset uses must be unique")
        if set(self.allowed_uses) & set(self.forbidden_uses):
            raise ValueError("dataset allowed and forbidden uses overlap")
        if (
            "live_order" not in self.forbidden_uses
            or "fresh_holdout_claim" not in self.forbidden_uses
        ):
            raise ValueError("external datasets must forbid live orders and fresh-holdout claims")
        if (
            not self.license.market_data_rights_reviewed
            and "redistribution" not in self.forbidden_uses
        ):
            raise ValueError("unreviewed market-data rights must forbid redistribution")
        if not self.license.market_data_rights_reviewed and self.license.redistribution_permitted:
            raise ValueError("unreviewed market-data rights cannot permit redistribution")
        if self.usage_level is DatasetUsageLevel.BACKTEST_RESEARCH and not (
            self.semantics.historical_membership
        ):
            raise ValueError("backtest research requires historical membership semantics")
        if self.usage_level in (
            DatasetUsageLevel.EXECUTION_QUALIFIED,
            DatasetUsageLevel.PROSPECTIVE,
        ) and not (
            self.semantics.raw_price_recoverable
            and self.semantics.corporate_actions_officially_verified
            and self.artifacts.archive_sha256
            and self.artifacts.manifest_sha256
        ):
            raise ValueError("execution-qualified data requires raw and official action evidence")
        self._validate_urls()
        return self

    def require_use(self, requested_use: str, validation: DatasetValidation | None = None) -> None:
        """Reject every undeclared, forbidden or insufficiently qualified use."""
        if requested_use in self.forbidden_uses or requested_use not in self.allowed_uses:
            raise DatasetRegistryError(f"dataset use is not allowed: {requested_use}")
        ranks = {level: index for index, level in enumerate(DatasetUsageLevel)}
        minimum = {
            "engineering": DatasetUsageLevel.FIXTURE_ONLY,
            "fixture": DatasetUsageLevel.FIXTURE_ONLY,
            "engine_reconciliation": DatasetUsageLevel.FIXTURE_ONLY,
            "exploratory_research": DatasetUsageLevel.RESEARCH_ADJUSTED_ONLY,
            "regime_label": DatasetUsageLevel.RESEARCH_ADJUSTED_ONLY,
            "external_retrospective_test": DatasetUsageLevel.BACKTEST_RESEARCH,
            "execution": DatasetUsageLevel.EXECUTION_QUALIFIED,
            "prospective": DatasetUsageLevel.PROSPECTIVE,
        }.get(requested_use)
        if minimum is None or ranks[self.usage_level] < ranks[minimum]:
            raise DatasetRegistryError("dataset usage level is insufficient")
        if minimum is not DatasetUsageLevel.FIXTURE_ONLY and (
            self.qualification_status != "QUALIFIED"
            or validation is None
            or not validation.qualified
            or validation.reasons
            or validation.dataset_id != self.dataset_id
            or validation.registry_sha256 != self.identity_sha256
        ):
            raise DatasetRegistryError("dataset has no qualified local validation")

    def _validate_urls(self) -> None:
        if (
            self.source_release_kind == "commit_snapshot"
            and self.source_release != f"commit-{self.source_commit}"
        ):
            raise ValueError("commit snapshot release must bind the source commit")
        for url in (self.artifacts.archive_url, self.artifacts.manifest_url):
            if url is None:
                continue
            if url.scheme != "https" or url.host != "github.com":
                raise ValueError("dataset artifact URL must use github.com HTTPS")
            if self.source_release_kind == "github_release":
                expected = f"/{self.source_repository}/releases/download/{self.source_release}/"
                if not (url.path or "").startswith(expected):
                    raise ValueError("dataset artifact URL differs from repository or release pin")
            else:
                expected = f"/{self.source_repository}/archive/{self.source_commit}"
                if (url.path or "") not in (f"{expected}.tar.gz", f"{expected}.zip"):
                    raise ValueError("snapshot artifact URL differs from repository or commit pin")
        if self.artifacts.manifest_url is not None:
            bindings = set(self.artifacts.manifest_bindings.values())
            if self.source_release not in bindings or self.source_commit not in bindings:
                raise ValueError("manifest bindings must include source release and commit pins")


class DatasetValidation(_StrictModel):
    """Machine-readable result of local registry and artifact validation."""

    dataset_id: str
    registry_sha256: str
    qualified: bool
    reasons: tuple[str, ...]
    archive_path: str | None
    manifest_path: str | None


Fetcher = Callable[[str], bytes]
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SEALED_EXTERNAL_ROOT = Path("/srv/quant-v2/sealed_holdout/data/external")


def load_dataset_registry(path: Path) -> DatasetRegistry:
    """Load one strict registry without contacting its source repository."""
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    try:
        return DatasetRegistry.model_validate(payload)
    except ValueError as error:
        raise DatasetRegistryError(f"invalid dataset registry: {path}") from error


def list_dataset_registries(root: Path) -> tuple[DatasetRegistry, ...]:
    """Return all registries in stable dataset-id order."""
    records = tuple(load_dataset_registry(path) for path in sorted(root.glob("*.yaml")))
    identities = [record.dataset_id for record in records]
    if len(identities) != len(set(identities)):
        raise DatasetRegistryError("dataset registry IDs must be unique")
    return tuple(sorted(records, key=lambda record: record.dataset_id))


def validate_dataset(path: Path, data_root: Path) -> DatasetValidation:
    """Validate registry semantics and locally captured bytes without network access."""
    _require_v2_data_root(data_root)
    registry = load_dataset_registry(path)
    reasons: list[str] = []
    archive_path = _artifact_path(registry, data_root, "archive")
    manifest_path = _artifact_path(registry, data_root, "manifest")
    if registry.usage_level is not DatasetUsageLevel.FIXTURE_ONLY:
        if not registry.artifacts.archive_sha256:
            reasons.append("archive_sha256_missing")
        if not registry.artifacts.manifest_sha256:
            reasons.append("manifest_sha256_missing")
        if registry.coverage.first_date is None or registry.coverage.last_date is None:
            reasons.append("coverage_unverified")
    for label, local, expected in (
        ("archive", archive_path, registry.artifacts.archive_sha256),
        ("manifest", manifest_path, registry.artifacts.manifest_sha256),
    ):
        if expected and (local is None or not local.is_file()):
            reasons.append(f"{label}_not_captured")
        elif expected and local is not None and _file_sha256(local) != expected:
            reasons.append(f"{label}_sha256_mismatch")
    if manifest_path and manifest_path.is_file():
        reasons.extend(_manifest_binding_reasons(registry, manifest_path.read_bytes()))
    return DatasetValidation(
        dataset_id=registry.dataset_id,
        registry_sha256=registry.identity_sha256,
        qualified=not reasons and registry.qualification_status == "QUALIFIED",
        reasons=tuple(
            reasons or (() if registry.qualification_status == "QUALIFIED" else ("status_pending",))
        ),
        archive_path=archive_path.as_posix() if archive_path else None,
        manifest_path=manifest_path.as_posix() if manifest_path else None,
    )


def capture_dataset(
    path: Path,
    data_root: Path,
    *,
    allow_network: bool,
    fetcher: Fetcher | None = None,
    captured_at: datetime | None = None,
) -> tuple[Path, ...]:
    """Capture only pre-hashed HTTPS artifacts into immutable content-addressed storage."""
    if not allow_network:
        raise DatasetRegistryError("--allow-network is required for dataset capture")
    _require_v2_data_root(data_root)
    registry = load_dataset_registry(path)
    captured: list[Path] = []
    for label, url, expected in (
        ("manifest", registry.artifacts.manifest_url, registry.artifacts.manifest_sha256),
        ("archive", registry.artifacts.archive_url, registry.artifacts.archive_sha256),
    ):
        if url is None:
            continue
        if expected is None:
            raise DatasetRegistryError(f"{label} cannot be captured without a pinned SHA-256")
        suffix = Path(url.path or "").name or f"{label}.bin"
        destination = data_root / registry.dataset_id / expected / suffix
        if fetcher is not None:
            content = fetcher(str(url))
            if sha256(content).hexdigest() != expected:
                raise DatasetRegistryError(f"{label} SHA-256 differs from the registry")
            if label == "manifest" and _manifest_binding_reasons(registry, content):
                raise DatasetRegistryError("manifest content differs from repository pins")
            write_immutable(destination, content)
        else:
            _fetch_to_immutable(str(url), destination, expected)
            if label == "manifest" and _manifest_binding_reasons(
                registry, destination.read_bytes()
            ):
                raise DatasetRegistryError("manifest content differs from repository pins")
        captured.append(destination)
    if not captured:
        raise DatasetRegistryError("dataset registry has no capturable pre-hashed artifacts")
    receipt = {
        "schema_version": 1,
        "dataset_id": registry.dataset_id,
        "source_repository": registry.source_repository,
        "source_commit": registry.source_commit,
        "source_release": registry.source_release,
        "retrieved_at_utc": (captured_at or datetime.now(UTC)).isoformat(),
        "registry_sha256": registry.identity_sha256,
        "registry_file_sha256": sha256(path.read_bytes()).hexdigest(),
        "captured": [
            {"path": item.relative_to(data_root).as_posix(), "sha256": item.parent.name}
            for item in captured
        ],
    }
    encoded = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    receipt_id = sha256(encoded).hexdigest()
    receipt_path = data_root / registry.dataset_id / "receipts" / f"{receipt_id}.json"
    write_immutable(receipt_path, encoded)
    return (*captured, receipt_path)


def _artifact_path(
    registry: DatasetRegistry, data_root: Path, label: Literal["archive", "manifest"]
) -> Path | None:
    expected = (
        registry.artifacts.archive_sha256
        if label == "archive"
        else registry.artifacts.manifest_sha256
    )
    url = registry.artifacts.archive_url if label == "archive" else registry.artifacts.manifest_url
    if expected is None or url is None:
        return None
    return (
        data_root / registry.dataset_id / expected / (Path(url.path or "").name or f"{label}.bin")
    )


def _fetch_to_immutable(url: str, destination: Path, expected: str) -> None:
    """Stream a large GitHub artifact through SHA-256 into an immutable destination."""
    if not url.startswith("https://github.com/"):
        raise DatasetRegistryError("dataset capture only accepts github.com HTTPS URLs")
    last_error: OSError | None = None
    for attempt in range(3):
        try:
            _stream_to_immutable_once(url, destination, expected)
            return
        except OSError as error:
            last_error = error
            if attempt < 2:
                time.sleep(0.2 * (attempt + 1))
    raise DatasetRegistryError(f"unable to capture dataset artifact: {url}") from last_error


def _stream_to_immutable_once(url: str, destination: Path, expected: str) -> None:
    """Perform one bounded-memory HTTPS transfer attempt."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    temporary = Path(temporary_name)
    digest = sha256()
    request = Request(url, headers={"User-Agent": "quant-stack-v2-dataset/1.0"})
    try:
        with os.fdopen(descriptor, "wb") as output, urlopen(request, timeout=30) as response:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
                digest.update(chunk)
            output.flush()
            os.fsync(output.fileno())
        if digest.hexdigest() != expected:
            raise DatasetRegistryError("captured artifact SHA-256 differs from the registry")
        try:
            os.link(temporary, destination)
        except FileExistsError:
            if _file_sha256(destination) != expected:
                raise DatasetRegistryError(
                    "existing dataset snapshot conflicts with its hash"
                ) from None
    finally:
        temporary.unlink(missing_ok=True)


def _file_sha256(path: Path) -> str:
    """Hash a potentially large local archive without reading it into memory."""
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_binding_reasons(registry: DatasetRegistry, content: bytes) -> list[str]:
    if not registry.artifacts.manifest_bindings:
        return []
    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return ["manifest_not_json"]
    if not isinstance(payload, dict):
        return ["manifest_not_mapping"]
    return [
        f"manifest_binding_mismatch:{field}"
        for field, expected in registry.artifacts.manifest_bindings.items()
        if str(payload.get(field)) != expected
    ]


def _require_v2_data_root(path: Path) -> None:
    """Prevent V2 capture and validation from being redirected into V1 authorities."""
    resolved = path.resolve()
    repository_data = REPOSITORY_ROOT / "data"
    if resolved.is_relative_to(repository_data) and resolved != repository_data / "external":
        raise DatasetRegistryError("V2 dataset root must not be nested in a V1 data namespace")
    if resolved.is_relative_to(REPOSITORY_ROOT) and resolved != repository_data / "external":
        raise DatasetRegistryError("V2 dataset root must be the repository data/external root")
    if resolved == SEALED_EXTERNAL_ROOT:
        return
    if resolved.name != "external" or resolved.parent.name != "data":
        raise DatasetRegistryError("V2 dataset root must end with data/external")
