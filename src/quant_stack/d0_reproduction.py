"""Actual-data deterministic reproduction evidence for D0 causal-adjusted datasets."""

from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path

from quant_stack.data.canonical import CANONICAL_ALGORITHM_VERSION, persist_causal_adjusted_dataset
from quant_stack.data.corporate_actions import load_corporate_action_ledger
from quant_stack.data.evidence import corporate_action_evidence_archive_path
from quant_stack.data.models import CanonicalDatasetManifest
from quant_stack.data.provider_series import load_provider_series
from quant_stack.snapshot import write_immutable


@dataclass(frozen=True)
class CausalReproductionReport:
    """Evidence that one immutable raw input and ledger reproduce the same causal output."""

    status: str
    source_manifest_id: str
    source_provider: str
    ledger_sha256: str
    source_registry_sha256: str
    adjustment_algorithm_version: str
    git_commit: str
    expected_causal_manifest_id: str
    observed_causal_manifest_id: str
    expected_output_sha256: str
    observed_output_sha256: str


def reproduce_causal_dataset(
    provider_manifest_id: str,
    ledger_path: Path,
    expected_manifest_path: Path,
    data_root: Path,
    source_registry_path: Path,
    git_commit: str,
) -> CausalReproductionReport:
    """Rebuild one selected provider series in isolation and require byte-identical output."""
    provider, raw_bars = load_provider_series(provider_manifest_id, data_root)
    expected = CanonicalDatasetManifest.model_validate_json(
        expected_manifest_path.read_text(encoding="utf-8")
    )
    ledger = load_corporate_action_ledger(ledger_path)
    with tempfile.TemporaryDirectory(prefix="quant-stack-d0-rebuild-") as temporary:
        rebuild_root = Path(temporary)
        for event in ledger.events:
            for evidence in (event.evidence, event.availability_evidence, event.value_evidence):
                if evidence is None:
                    continue
                source = corporate_action_evidence_archive_path(data_root, evidence)
                destination = corporate_action_evidence_archive_path(rebuild_root, evidence)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
        observed = persist_causal_adjusted_dataset(provider, raw_bars, ledger, rebuild_root)
    status = (
        "pass"
        if observed.manifest_id == expected.manifest_id
        and observed.output_file.sha256 == expected.output_file.sha256
        else "blocked"
    )
    return CausalReproductionReport(
        status=status,
        source_manifest_id=provider.manifest_id,
        source_provider=provider.provider.value,
        ledger_sha256=sha256(ledger_path.read_bytes()).hexdigest(),
        source_registry_sha256=sha256(source_registry_path.read_bytes()).hexdigest(),
        adjustment_algorithm_version=CANONICAL_ALGORITHM_VERSION,
        git_commit=git_commit,
        expected_causal_manifest_id=expected.manifest_id,
        observed_causal_manifest_id=observed.manifest_id,
        expected_output_sha256=expected.output_file.sha256,
        observed_output_sha256=observed.output_file.sha256,
    )


def reproduce_sina_causal_dataset(
    provider_manifest_path: Path,
    ledger_path: Path,
    expected_manifest_path: Path,
    data_root: Path,
) -> CausalReproductionReport:
    """Compatibility wrapper for the accepted Issue 003 Sina reproduction interface."""
    payload = json.loads(provider_manifest_path.read_text(encoding="utf-8"))
    manifest_id = payload.get("manifest_id")
    if not isinstance(manifest_id, str):
        raise ValueError("provider manifest does not contain a manifest ID")
    return reproduce_causal_dataset(
        manifest_id,
        ledger_path,
        expected_manifest_path,
        data_root,
        Path("configs/data_qualification/d0_sources_v1.yaml"),
        "legacy-wrapper",
    )


def persist_causal_reproduction_report(
    report: CausalReproductionReport, artifact_root: Path
) -> Path:
    """Write one immutable reproduction result addressed by its complete stable content."""
    content = json.dumps(asdict(report), sort_keys=True, separators=(",", ":")).encode() + b"\n"
    report_id = sha256(content).hexdigest()
    path = artifact_root / report_id / "causal_reproduction.json"
    write_immutable(path, content)
    return path
