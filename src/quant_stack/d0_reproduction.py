"""Actual-data deterministic reproduction evidence for D0 causal-adjusted datasets."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path

from quant_stack.data.canonical import persist_causal_adjusted_dataset
from quant_stack.data.corporate_actions import load_corporate_action_ledger
from quant_stack.data.models import CanonicalDatasetManifest, ProviderId, ProviderSeriesManifest
from quant_stack.data.sina_etf import load_sina_provider_bars
from quant_stack.snapshot import write_immutable


@dataclass(frozen=True)
class CausalReproductionReport:
    """Evidence that one immutable raw input and ledger reproduce the same causal output."""

    status: str
    source_manifest_id: str
    ledger_sha256: str
    expected_causal_manifest_id: str
    observed_causal_manifest_id: str
    expected_output_sha256: str
    observed_output_sha256: str


def reproduce_sina_causal_dataset(
    provider_manifest_path: Path,
    ledger_path: Path,
    expected_manifest_path: Path,
    data_root: Path,
) -> CausalReproductionReport:
    """Re-run the frozen causal algorithm and require byte-identical canonical identity."""
    provider = ProviderSeriesManifest.model_validate_json(
        provider_manifest_path.read_text(encoding="utf-8")
    )
    if provider.provider is not ProviderId.SINA:
        raise ValueError("D0 reproduction currently requires a Sina provider-native raw manifest")
    expected = CanonicalDatasetManifest.model_validate_json(
        expected_manifest_path.read_text(encoding="utf-8")
    )
    ledger = load_corporate_action_ledger(ledger_path)
    observed = persist_causal_adjusted_dataset(
        provider, load_sina_provider_bars(provider, data_root), ledger, data_root
    )
    status = (
        "pass"
        if observed.manifest_id == expected.manifest_id
        and observed.output_file.sha256 == expected.output_file.sha256
        else "blocked"
    )
    return CausalReproductionReport(
        status=status,
        source_manifest_id=provider.manifest_id,
        ledger_sha256=sha256(ledger_path.read_bytes()).hexdigest(),
        expected_causal_manifest_id=expected.manifest_id,
        observed_causal_manifest_id=observed.manifest_id,
        expected_output_sha256=expected.output_file.sha256,
        observed_output_sha256=observed.output_file.sha256,
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
