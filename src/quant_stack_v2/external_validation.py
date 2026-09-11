"""Fail-closed V2-010 external-history qualification contracts."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path

from quant_stack.snapshot import write_immutable

ALLOWED_MARKETS = {"CSI500_CNY", "GLOBAL_ETF_USD"}


class ExternalValidationError(ValueError):
    """Raised when external-history evidence would bypass a V2 qualification gate."""


@dataclass(frozen=True)
class TrustedArtifact:
    """A content-addressed artifact rooted under one reviewed V2 evidence directory."""

    relative_path: str
    sha256: str


@dataclass(frozen=True)
class ExternalQualification:
    """One immutable external-market qualification state, never inferred from adjusted prices."""

    schema_version: int
    dataset_id: str
    market: str
    currency: str
    source_approval: str
    raw_manifest_sha256: str | None
    calendar_sha256: str | None
    corporate_actions_sha256: str | None
    pit_membership_sha256: str | None
    cost_model_sha256: str | None
    reproducibility_sha256: str | None
    status: str
    reasons: tuple[str, ...]

    @property
    def identity_sha256(self) -> str:
        """Return the stable qualification identity."""
        return sha256(_canonical_json(asdict(self))).hexdigest()


@dataclass(frozen=True)
class ExternalBlindTestPrecommit:
    """Frozen identities required before any V2 external historical test can execute."""

    strategy_id: str
    market: str
    currency: str
    qualification_sha256: str
    input_manifest_sha256: str
    code_commit: str
    config_sha256: str
    cost_model_sha256: str
    split_sha256: str
    benchmark_id: str
    status: str

    @property
    def identity_sha256(self) -> str:
        """Return a deterministic external-test request identity."""
        return sha256(_canonical_json(asdict(self))).hexdigest()


def qualify_external_market(
    *,
    dataset_id: str,
    market: str,
    currency: str,
    source_approval: str,
    evidence_root: Path | None = None,
    evidence: dict[str, TrustedArtifact] | None = None,
) -> ExternalQualification:
    """Produce qualification evidence without network access or a partial promotion."""
    if market not in ALLOWED_MARKETS or not dataset_id:
        raise ExternalValidationError("unknown V2 external market or dataset")
    expected_currency = "CNY" if market == "CSI500_CNY" else "USD"
    if currency != expected_currency:
        raise ExternalValidationError("external market and currency must not be mixed")
    reasons: list[str] = []
    if source_approval != "APPROVED":
        reasons.append("source_approval_pending")
    required_names = (
        "raw_manifest",
        "calendar",
        "corporate_actions",
        "pit_membership",
        "cost_model",
        "reproducibility",
    )
    evidence = evidence or {}
    verified: dict[str, str | None] = {}
    for name in required_names:
        artifact = evidence.get(name)
        if artifact is None or evidence_root is None:
            reasons.append(f"{name}_missing")
            verified[name] = None
            continue
        verified[name] = _verify_artifact(evidence_root, artifact, name, reasons)
    return ExternalQualification(
        schema_version=1,
        dataset_id=dataset_id,
        market=market,
        currency=currency,
        source_approval=source_approval,
        raw_manifest_sha256=verified["raw_manifest"],
        calendar_sha256=verified["calendar"],
        corporate_actions_sha256=verified["corporate_actions"],
        pit_membership_sha256=verified["pit_membership"],
        cost_model_sha256=verified["cost_model"],
        reproducibility_sha256=verified["reproducibility"],
        status="QUALIFIED" if not reasons else "BLOCKED_DATA",
        reasons=tuple(sorted(reasons)),
    )


def create_external_blind_test_precommit(
    qualification: ExternalQualification,
    *,
    strategy_id: str,
    input_manifest_sha256: str,
    code_commit: str,
    config_sha256: str,
    split_sha256: str,
    benchmark_id: str,
) -> ExternalBlindTestPrecommit:
    """Refuse a blind-test request until all external evidence has independently qualified."""
    if qualification.status != "QUALIFIED":
        raise ExternalValidationError("external blind test requires QUALIFIED market evidence")
    required = (input_manifest_sha256, config_sha256, split_sha256, qualification.cost_model_sha256)
    if (
        not strategy_id
        or not benchmark_id
        or any(value is None or len(value) != 64 for value in required)
    ):
        raise ExternalValidationError("external blind-test precommit lacks immutable identities")
    if len(code_commit) != 40:
        raise ExternalValidationError("external blind-test precommit requires a Git commit")
    cost_model_sha256 = qualification.cost_model_sha256
    if cost_model_sha256 is None:
        raise ExternalValidationError("external blind-test precommit lacks a cost-model identity")
    return ExternalBlindTestPrecommit(
        strategy_id=strategy_id,
        market=qualification.market,
        currency=qualification.currency,
        qualification_sha256=qualification.identity_sha256,
        input_manifest_sha256=input_manifest_sha256,
        code_commit=code_commit,
        config_sha256=config_sha256,
        cost_model_sha256=cost_model_sha256,
        split_sha256=split_sha256,
        benchmark_id=benchmark_id,
        status="FROZEN_NOT_EXECUTED",
    )


def persist_external_qualification(report: ExternalQualification, artifact_root: Path) -> Path:
    """Persist a blocked or qualified external-data report immutably."""
    path = artifact_root / "external_qualification" / f"{report.identity_sha256}.json"
    write_immutable(path, _canonical_json(asdict(report)) + b"\n")
    return path


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _verify_artifact(
    root: Path, artifact: TrustedArtifact, name: str, reasons: list[str]
) -> str | None:
    if len(artifact.sha256) != 64:
        reasons.append(f"{name}_invalid_sha256")
        return None
    path = (root / artifact.relative_path).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        reasons.append(f"{name}_untrusted_path")
        return None
    actual = sha256(path.read_bytes()).hexdigest()
    if actual != artifact.sha256:
        reasons.append(f"{name}_sha256_mismatch")
        return None
    return actual
