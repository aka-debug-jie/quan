import json
from hashlib import sha256
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from quant_stack.data_qualification import (
    _passing_reconciliation_report,
    persist_qualification_report,
    qualify_frozen_universe,
)


def _manifest(root: Path, symbol: str, basis: str, content: bytes) -> None:
    output = root / f"{symbol}-{basis}.parquet"
    table = pa.table(
        {
            "trading_date": pa.array(["2024-01-02", "2024-01-03"]),
            "close": pa.array([1.0, 1.0]),
        }
    )
    pq.write_table(table, output)
    raw = root / f"{symbol}-{basis}.csv"
    raw.write_bytes(content)
    manifest = {
        "manifest_id": f"{symbol}-{basis}",
        "request": {"instrument": {"symbol": symbol, "exchange": "SSE"}, "price_basis": basis},
        "first_captured_at": "2024-01-04T00:00:00Z",
        "coverage_complete": True,
        "raw_file": {"relative_path": raw.name, "sha256": sha256(content).hexdigest()},
        "normalized_file": {
            "relative_path": output.name,
            "sha256": sha256(output.read_bytes()).hexdigest(),
        },
    }
    manifests = root / "manifests"
    manifests.mkdir(exist_ok=True)
    (manifests / f"{symbol}-{basis}.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_qualification_reports_all_frozen_assets_not_only_known_missing_ones(
    tmp_path: Path,
) -> None:
    universe = tmp_path / "universe.yaml"
    universe.write_text(
        "universe_id: test\nversion: 1\ninstruments:\n"
        "  - symbol: A\n    exchange: SSE\n    effective_from: 2024-01-01\n"
        "  - symbol: B\n    exchange: SSE\n    effective_from: 2024-01-01\n",
        encoding="utf-8",
    )
    _manifest(tmp_path, "A", "raw", b"raw-a")
    _manifest(tmp_path, "A", "qfq", b"qfq-a")
    registry = tmp_path / "registry.yaml"
    registry.write_text(
        "registry_id: test\nversion: 1\nuniverse_sha256: "
        + sha256(universe.read_bytes()).hexdigest()
        + "\nassets:\n"
        + "  - symbol: A\n    exchange: SSE\n    canonical_raw_manifest_id: '"
        + "a" * 64
        + "'\n    cross_check_manifest_id: '"
        + "b" * 64
        + "'\n    official_inventory_complete: false\n"
        + "  - symbol: B\n    exchange: SSE\n    canonical_raw_manifest_id: '"
        + "c" * 64
        + "'\n    cross_check_manifest_id: '"
        + "d" * 64
        + "'\n    official_inventory_complete: false\n",
        encoding="utf-8",
    )
    report = qualify_frozen_universe(
        universe, tmp_path, tmp_path / "ledgers", source_registry_path=registry
    )
    assert [asset.symbol for asset in report.assets] == ["A", "B"]
    assert all(asset.result == "NOT_QUALIFIED" for asset in report.assets)
    assert report.assets[0].candidate_inventory.provider_factor_classification == (
        "EVENT_LEVEL_RECONCILED"
    )
    assert report.assets[0].candidate_inventory.unresolved_factor_change_points == 0
    assert not report.assets[0].inventory_complete
    assert "raw_coverage_missing" in report.assets[1].reasons
    assert report.assets[0].ledger_sha256 is None
    assert report.assets[0].cross_provider_report_id is None
    assert report.assets[0].deterministic_reproduction_report_id is None
    assert report.assets[0].official_event_count == 0
    first = persist_qualification_report(report, tmp_path / "artifacts")
    second = persist_qualification_report(report, tmp_path / "artifacts")
    assert first == second


def test_qualification_rejects_a_tampered_reconciliation_receipt(tmp_path: Path) -> None:
    payload: dict[str, object] = {
        "version": "2.0.0",
        "status": "pass",
        "source_manifest_id": "a" * 64,
        "cross_check_manifest_id": "b" * 64,
        "adjudicator_manifest_id": None,
        "overlap_sessions": 1,
        "mismatched_sessions": 0,
        "adjudicated_sessions": 0,
        "source_rejected_sessions": 0,
        "unexplained_mismatches": 0,
    }
    identity = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    report_id = sha256(identity).hexdigest()
    payload["report_id"] = report_id
    path = tmp_path / f"{report_id}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert _passing_reconciliation_report(tmp_path, "a" * 64, "b" * 64, None, 1, True) == report_id

    payload["overlap_sessions"] = 2
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert _passing_reconciliation_report(tmp_path, "a" * 64, "b" * 64, None, 1, True) is None
