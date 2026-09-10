from pathlib import Path

from quant_stack.d0_reproduction import CausalReproductionReport, persist_causal_reproduction_report


def test_reproduction_report_is_content_addressed_and_idempotent(tmp_path: Path) -> None:
    report = CausalReproductionReport(
        status="pass",
        source_manifest_id="source",
        ledger_sha256="ledger",
        expected_causal_manifest_id="expected",
        observed_causal_manifest_id="expected",
        expected_output_sha256="output",
        observed_output_sha256="output",
    )
    first = persist_causal_reproduction_report(report, tmp_path)
    second = persist_causal_reproduction_report(report, tmp_path)
    assert first == second
