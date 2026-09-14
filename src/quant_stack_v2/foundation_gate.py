"""Immutable V2 Foundation Gate evidence and fail-closed promotion decision."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path

from quant_stack.snapshot import write_immutable

REQUIRED_GATES = (
    "factor_semantics",
    "official_membership",
    "daily_audit",
    "official_trading_state",
    "free_evidence_reconciliation",
    "pit_membership",
)

# Tushare can add a provider cross-check when a user voluntarily supplies it,
# but no token, credits, or paid service is needed for the free-evidence gate.
OPTIONAL_PROVIDER_GATES = ("tushare_raw_reconciliation",)


@dataclass(frozen=True)
class GateEvidence:
    """One content-addressed evidence file accepted by the Foundation Gate."""

    name: str
    path: str
    sha256: str
    status: str


@dataclass(frozen=True)
class V2QualificationReport:
    """One immutable decision joining every evidence gate for a frozen study range."""

    schema_version: int
    universe: str
    research_effective_from: str
    research_effective_to: str
    import_report_sha256: str
    config_sha256: str
    code_commit: str
    evidence: tuple[GateEvidence, ...]
    status: str
    reasons: tuple[str, ...]

    @property
    def identity_sha256(self) -> str:
        """Return deterministic report identity without runtime timestamps."""
        return sha256(_canonical_json(asdict(self))).hexdigest()


def qualify_foundation(
    *,
    universe: str,
    research_effective_from: str,
    research_effective_to: str,
    import_report_sha256: str,
    config_sha256: str,
    code_commit: str,
    evidence: tuple[GateEvidence, ...],
) -> V2QualificationReport:
    """Join validated evidence records and block on every absent or failed gate."""
    if universe != "csi300" or len(import_report_sha256) != 64 or len(config_sha256) != 64:
        raise ValueError("Foundation Gate requires frozen CSI300 import and configuration hashes")
    if len(code_commit) != 40:
        raise ValueError("Foundation Gate requires the exact code commit")
    by_name = {item.name: item for item in evidence}
    allowed = set(REQUIRED_GATES) | set(OPTIONAL_PROVIDER_GATES)
    if len(by_name) != len(evidence) or set(by_name) - allowed:
        raise ValueError("Foundation Gate received unknown or duplicate evidence")
    reasons: list[str] = []
    for name in REQUIRED_GATES:
        item = by_name.get(name)
        if item is None:
            reasons.append(f"{name}_missing")
        elif len(item.sha256) != 64:
            reasons.append(f"{name}_invalid_hash")
        elif item.status != "QUALIFIED":
            reasons.append(f"{name}_not_qualified")
    return V2QualificationReport(
        schema_version=1,
        universe=universe,
        research_effective_from=research_effective_from,
        research_effective_to=research_effective_to,
        import_report_sha256=import_report_sha256,
        config_sha256=config_sha256,
        code_commit=code_commit,
        evidence=tuple(sorted(evidence, key=lambda item: item.name)),
        status="QUALIFIED" if not reasons else "BLOCKED_DATA",
        reasons=tuple(reasons),
    )


def persist_qualification(report: V2QualificationReport, artifact_root: Path) -> Path:
    """Persist a content-addressed gate decision without overwriting prior reports."""
    path = artifact_root / "foundation_gate" / f"{report.identity_sha256}.json"
    write_immutable(path, _canonical_json(asdict(report)) + b"\n")
    return path


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
