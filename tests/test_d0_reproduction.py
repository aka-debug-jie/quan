from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path

from quant_stack.d0_reproduction import (
    CausalReproductionReport,
    persist_causal_reproduction_report,
    reproduce_causal_dataset,
)
from quant_stack.data.canonical import persist_causal_adjusted_dataset
from quant_stack.data.corporate_actions import load_corporate_action_ledger
from quant_stack.data.evidence import corporate_action_evidence_archive_path
from quant_stack.data.models import ETFHistoryRequest, ETFUniverseInstrument, OfficialEvidence
from quant_stack.data.sina_etf import SinaHistoryPayload
from quant_stack.data.sse_official import (
    load_sse_provider_bars,
    persist_sse_daily_history,
)
from quant_stack.models import Exchange, PriceBasis


def test_reproduction_report_is_content_addressed_and_idempotent(tmp_path: Path) -> None:
    report = CausalReproductionReport(
        status="pass",
        source_manifest_id="source",
        source_provider="sina",
        ledger_sha256="ledger",
        source_registry_sha256="registry",
        adjustment_algorithm_version="1.0.0",
        git_commit="commit",
        expected_causal_manifest_id="expected",
        observed_causal_manifest_id="expected",
        expected_output_sha256="output",
        observed_output_sha256="output",
    )
    first = persist_causal_reproduction_report(report, tmp_path)
    second = persist_causal_reproduction_report(report, tmp_path)
    assert first == second


def test_reproduction_loads_registry_selected_sse_provider_in_isolation(tmp_path: Path) -> None:
    request = ETFHistoryRequest(
        instrument=ETFUniverseInstrument(
            symbol="510300", exchange=Exchange.SSE, effective_from=date(2024, 1, 1)
        ),
        start_date=date(2024, 1, 2),
        as_of_date=date(2024, 1, 3),
        price_basis=PriceBasis.RAW,
    )
    payload = SinaHistoryPayload(
        source_url="https://yunhq.sse.com.cn:32042/v1/sh1/dayk/510300",
        request_parameters={},
        http_metadata={":status": "200"},
        retrieved_at=datetime(2024, 1, 4, tzinfo=UTC),
        raw_bytes=(
            b'{"code":"510300","total":2,"kline":'
            b"[[20240102,10,10,10,10,100],[20240103,9,9,9,9,100]]}"
        ),
    )
    provider = persist_sse_daily_history(request, payload, tmp_path)
    evidence_body = b"official action"
    evidence = OfficialEvidence(
        url="https://example.invalid/action.pdf",
        sha256=sha256(evidence_body).hexdigest(),
        published_on=date(2024, 1, 2),
    )
    evidence_path = corporate_action_evidence_archive_path(tmp_path, evidence)
    evidence_path.parent.mkdir(parents=True)
    evidence_path.write_bytes(evidence_body)
    ledger_path = tmp_path / "ledger.yaml"
    ledger_path.write_text(
        """ledger_id: test
version: 1
instrument: {symbol: '510300', exchange: SSE, currency: CNY, asset_class: etf}
completeness: complete
events:
  - effective_date: 2024-01-03
    kind: cash_distribution
    cash_per_unit: '1'
    verification_status: official_evidence_chain_verified
    evidence: &e
      url: 'https://example.invalid/action.pdf'
      sha256: 'DIGEST'
      published_on: 2024-01-02
    availability_evidence: *e
    value_evidence: *e
""".replace("DIGEST", evidence.sha256),
        encoding="utf-8",
    )
    expected = persist_causal_adjusted_dataset(
        provider,
        load_sse_provider_bars(provider, tmp_path),
        load_corporate_action_ledger(ledger_path),
        tmp_path,
    )
    expected_path = tmp_path / "canonical" / "manifests" / f"{expected.manifest_id}.json"
    registry = tmp_path / "registry.yaml"
    registry.write_text("registry", encoding="utf-8")

    report = reproduce_causal_dataset(
        provider.manifest_id,
        ledger_path,
        expected_path,
        tmp_path,
        registry,
        "abc123",
    )

    assert report.status == "pass"
    assert report.source_provider == "sse_official"
    assert report.expected_output_sha256 == report.observed_output_sha256
