import json
from hashlib import sha256
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from quant_stack.data_qualification import persist_qualification_report, qualify_frozen_universe


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
    report = qualify_frozen_universe(universe, tmp_path, tmp_path / "ledgers")
    assert [asset.symbol for asset in report.assets] == ["A", "B"]
    assert all(asset.result == "NOT_QUALIFIED" for asset in report.assets)
    assert report.assets[0].candidate_inventory.unresolved_factor_change_points > 0
    assert "raw_coverage_missing" in report.assets[1].reasons
    first = persist_qualification_report(report, tmp_path / "artifacts")
    second = persist_qualification_report(report, tmp_path / "artifacts")
    assert first == second
