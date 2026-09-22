from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest
from fastapi.testclient import TestClient

from quant_console.api import create_app
from quant_console.config import ConsoleConfigError, load_config
from quant_console.demo import publish_demo
from quant_console.snapshot import SnapshotError, build_snapshot, load_current


def test_demo_api_is_explicit_and_safe(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    publish_demo(runtime)
    client = TestClient(create_app(runtime))
    overview = client.get("/api/v1/overview")
    assert overview.status_code == 200
    assert client.get("/api/v1/snapshot").json()["mode"] == "demo"
    assert overview.json()["economic_outcome"] == "DEMO_ONLY"
    experiments = client.get("/api/v1/experiments?page_size=100").json()
    artifact_id = experiments["items"][0]["artifact_id"]
    detail = client.get(f"/api/v1/experiments/{artifact_id}").json()
    assert detail["nav_series"][0]["nav"] == "1000000"
    assert "absolute" not in json.dumps(detail).lower()
    response = client.post(
        "/api/v1/exports/experiments",
        json={"artifact_ids": [artifact_id], "format": "csv"},
    )
    assert response.status_code == 200
    assert "position" not in response.text.lower()
    assert client.get("/api/v1/studies").status_code == 200
    assert client.get("/api/v1/signals").status_code == 200
    assert client.get("/api/v1/prospective").status_code == 200
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/experiments?sort=unsupported").status_code == 422
    evidence = client.get("/api/v1/evidence/demo:synthetic-run-001")
    assert evidence.json()["source_kind"] == "synthetic_fixture"
    comparison = client.post(
        "/api/v1/comparisons/validate",
        json={"artifact_ids": [artifact_id, artifact_id]},
    )
    assert comparison.json()["mode"] == "COMPARABLE"
    assert client.post("/api/v1/snapshot/reload").status_code == 409


def test_host_origin_and_unknown_identifiers_are_rejected(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    publish_demo(runtime)
    client = TestClient(create_app(runtime))
    assert client.get("/api/v1/overview", headers={"host": "evil.example"}).status_code == 400
    assert (
        client.get(
            "/api/v1/overview",
            headers={"origin": "https://evil.example"},
        ).status_code
        == 403
    )
    assert client.get("/api/v1/experiments/../../etc/passwd").status_code in {404, 405}
    assert client.get("/api/v1/evidence/unknown").status_code == 404


def test_comparison_marks_mismatched_scenarios_descriptive_only(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    publish_demo(runtime)
    snapshot = load_current(runtime)
    first = snapshot["experiments"][0]
    second = json.loads(json.dumps(first))
    second["artifact_id"] = "demo:synthetic-run-002"
    second["experiment_id"] = "SYNTHETIC_B"
    second["compatibility"]["scenario_id"] = "DEMO_T2"
    snapshot["experiments"].append(second)
    snapshot["experiment_details"][second["artifact_id"]] = second
    pointer = json.loads((runtime / "current.json").read_text())
    path = runtime / "snapshots" / pointer["snapshot_id"] / "snapshot.json"
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    client = TestClient(create_app(runtime))
    result = client.post(
        "/api/v1/comparisons/validate",
        json={"artifact_ids": [first["artifact_id"], second["artifact_id"]]},
    ).json()
    assert result["mode"] == "DESCRIPTIVE_ONLY"
    assert "scenario_id 不一致" in result["reasons"]


def test_real_adapter_keeps_absolute_and_benchmark_validity_separate(tmp_path: Path) -> None:
    config_path = _fixture_sources(tmp_path)
    runtime = tmp_path / "runtime"
    build_snapshot(load_config(config_path), runtime)
    snapshot = load_current(runtime)
    assert snapshot["overview"] == {
        "current_stage": "CN_QUANT_RESEARCH_UPGRADE_V1_COMPLETE",
        "registered_runs": 2,
        "valid_runs": 1,
        "not_evaluable_runs": 1,
        "retained_candidates": 0,
        "legacy_invalid_engineering_runs": 0,
        "economic_outcome": "NO_PROMOTABLE_CANDIDATE",
        "latest_prospective_date": "2026-09-22",
        "prospective_status": "OPERATIONS_LOOP_RC",
        "warnings": ["DEGRADED_PROVIDER_FAILURES", "MIXED_PROSPECTIVE_INPUT"],
    }
    candidate = next(
        item for item in snapshot["experiments"] if item["strategy_id"] == "AF7_TOP50_D20_EQ"
    )
    assert candidate["data_evaluability"] == "VALID"
    assert candidate["metrics"]["cagr"]["value"] == -0.05
    assert candidate["benchmark_comparability"] == "MATCHED_BENCHMARK_NOT_EVALUABLE"
    assert candidate["economic_outcome"] == "NOT_EVALUABLE"
    detail = snapshot["experiment_details"][candidate["artifact_id"]]
    assert detail["benchmark_comparability"] == "MATCHED_BENCHMARK_NOT_EVALUABLE"
    assert len(detail["nav_series"]) == 2
    assert snapshot["prospective"]["accounts"]["fully_prospective_v1"]["status"] == "NOT_STARTED"


def test_hash_conflict_fails_without_replacing_current_snapshot(tmp_path: Path) -> None:
    config_path = _fixture_sources(tmp_path)
    runtime = tmp_path / "runtime"
    config = load_config(config_path)
    build_snapshot(config, runtime)
    previous = (runtime / "current.json").read_bytes()
    matrix = (
        config.upgrade_v1.artifacts
        / "matrix"
        / f"{_json(config.upgrade_v1.manifest)['matrix_sha256']}.json"
    )
    matrix.write_text("{}", encoding="utf-8")
    with pytest.raises(SnapshotError, match="hash mismatch"):
        build_snapshot(config, runtime)
    assert (runtime / "current.json").read_bytes() == previous
    assert _json(runtime / "last_refresh.json")["status"] == "FAIL"


def test_config_rejects_demo_and_missing_fields(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("mode='demo'\n", encoding="utf-8")
    with pytest.raises(ConsoleConfigError):
        load_config(path)


def test_web_modules_do_not_import_runners_brokers_or_providers() -> None:
    package = Path(__file__).parents[1] / "src" / "quant_console"
    text = "\n".join(
        (package / name).read_text(encoding="utf-8")
        for name in ("api.py", "snapshot.py", "config.py", "models.py")
    )
    for forbidden in ("prospective_runner", "paper_broker", "akshare", "requests", "subprocess"):
        assert forbidden not in text


def _fixture_sources(tmp_path: Path) -> Path:
    v3_artifacts = tmp_path / "v3-artifacts"
    upgrade_artifacts = tmp_path / "upgrade-artifacts"
    prospective = tmp_path / "prospective"
    for root in (v3_artifacts, upgrade_artifacts):
        for folder in ("matrix", "runs", "diagnostics", "attribution", "measurement"):
            (root / folder).mkdir(parents=True, exist_ok=True)
    v3_result_id = "1" * 64
    _write_run(v3_artifacts, v3_result_id, "B00_LIQ20_D20", "BASE", valid=True)
    v3_matrix = {
        "schema_version": 1,
        "benchmark_id": "B00_LIQ20_D20",
        "ECONOMIC_OUTCOME": "NO_HISTORICAL_COST_ADJUSTED_EDGE",
        "result_identities": {"B00_LIQ20_D20": v3_result_id},
    }
    v3_matrix_sha = _write_content(v3_artifacts / "matrix", v3_matrix)
    diagnostics_sha = _write_content(
        v3_artifacts / "diagnostics",
        {"schema_version": 1, "summaries": {"open_to_open_20": {"mean_rank_ic": 0.01}}},
    )
    v3_manifest = tmp_path / "v3-manifest.json"
    _dump(
        v3_manifest,
        {
            "schema_version": 1,
            "matrix_sha256": v3_matrix_sha,
            "signal_diagnostics_sha256": diagnostics_sha,
            "IMPLEMENTATION_STATUS": "IMPLEMENTED",
            "RESEARCH_VALIDITY": "VALID_RETROSPECTIVE",
            "ECONOMIC_OUTCOME": "NO_HISTORICAL_COST_ADJUSTED_EDGE",
            "DATA_USE_LEVEL": "PRIVATE_RESEARCH_ONLY",
        },
    )
    candidate_id, benchmark_id = "2" * 64, "3" * 64
    _write_run(upgrade_artifacts, candidate_id, "AF7_TOP50_D20_EQ", "REAL_T1_1M", valid=True)
    _write_run(upgrade_artifacts, benchmark_id, "B50_LIQ50_D20", "REAL_T1_1M", valid=False)
    upgrade_matrix = {
        "schema_version": 1,
        "status": "COMPLETE",
        "candidate_outcomes": {"AF7_TOP50_D20_EQ": "NOT_EVALUABLE"},
        "result_identities": {
            "AF7_TOP50_D20_EQ__REAL_T1_1M": candidate_id,
            "B50_LIQ50_D20__REAL_T1_1M": benchmark_id,
        },
    }
    upgrade_matrix_sha = _write_content(upgrade_artifacts / "matrix", upgrade_matrix)
    attribution_sha = _write_content(
        upgrade_artifacts / "attribution", {"schema_version": 1, "signals": {}}
    )
    measurement_sha = _write_content(
        upgrade_artifacts / "measurement", {"schema_version": 1, "summaries": {}}
    )
    upgrade_manifest = tmp_path / "upgrade-manifest.json"
    _dump(
        upgrade_manifest,
        {
            "schema_version": 1,
            "matrix_sha256": upgrade_matrix_sha,
            "signal_attribution_sha256": attribution_sha,
            "measurement_audit_sha256": measurement_sha,
            "invalid_engineering_prefixed_runs_retained": 0,
            "retained_candidates": 0,
            "IMPLEMENTATION_STATUS": "COMPLETE",
            "RESEARCH_VALIDITY": "MIXED",
            "ECONOMIC_OUTCOME": "NO_PROMOTABLE_CANDIDATE",
            "DATA_USE_LEVEL": "PRIVATE_RESEARCH_ONLY",
        },
    )
    (prospective / "daily").mkdir(parents=True)
    (prospective / "diagnostics").mkdir()
    daily = {
        "schema_version": 2,
        "trading_date": "2026-09-22",
        "OPERATIONS_ACCEPTANCE_STATUS": "OPERATIONS_LOOP_RC",
        "ENGINEERING_STATUS": "DAILY_RUN_COMPLETE",
        "INPUT_STATUS": "MIXED_PROSPECTIVE_INPUT",
        "DATA_CAPTURE_STATUS": "DEGRADED_PROVIDER_FAILURES",
        "SHADOW_SIGNAL_STATUS": "SIGNAL_EMITTED",
        "PAPER_ACCOUNT_STATUS": "RECONCILED_LOCAL_ONLY",
        "paper_account_phase": "engineering_warm_start",
        "PROFITABILITY_STATUS": "INSUFFICIENT_PROSPECTIVE_EVIDENCE",
        "coverage": 292,
        "nav": "1000000",
        "cash": "50000",
        "positions": ["demo"],
        "top": ["demo"],
        "rejections_today": [],
        "receipt_sha256": "a" * 64,
    }
    encoded = json.dumps(daily, sort_keys=True, separators=(",", ":")).encode()
    digest = sha256(encoded).hexdigest()
    (prospective / "daily" / f"2026-09-22-{digest}.json").write_bytes(encoded)
    diagnostic_encoded = json.dumps({"schema_version": 2, "mean_ic": None}).encode()
    (prospective / "diagnostics" / "2026-09-22-demo.json").write_bytes(diagnostic_encoded)
    acceptance = tmp_path / "acceptance.json"
    _dump(acceptance, {"schema_version": 1, "acceptance_status": "OPERATIONS_LOOP_RC"})
    config = tmp_path / "sources.toml"
    config.write_text(
        "\n".join(
            (
                'mode = "real"',
                "[historical_v3]",
                f'manifest = "{v3_manifest}"',
                f'artifacts = "{v3_artifacts}"',
                "[upgrade_v1]",
                f'manifest = "{upgrade_manifest}"',
                f'artifacts = "{upgrade_artifacts}"',
                "[prospective]",
                f'artifacts = "{prospective}"',
                f'acceptance_manifest = "{acceptance}"',
            )
        ),
        encoding="utf-8",
    )
    return config


def _write_run(root: Path, identity: str, strategy: str, scenario: str, *, valid: bool) -> None:
    destination = root / "runs" / identity
    destination.mkdir(parents=True)
    experiment_id = strategy if scenario == "BASE" else f"{strategy}__{scenario}"
    result: dict[str, Any] = {
        "schema_version": 1,
        "run_identity": identity,
        "experiment_id": experiment_id,
        "strategy_id": strategy,
        "scenario_id": scenario,
        "IMPLEMENTATION_STATUS": "IMPLEMENTED",
        "HISTORICAL_RUN_STATUS": "COMPLETE_REAL_DATA" if valid else "NOT_EVALUABLE_REAL_DATA",
        "RESEARCH_VALIDITY": "VALID" if valid else "NOT_EVALUABLE",
        "DATA_USE_LEVEL": "PRIVATE_RESEARCH_ONLY",
        "identities": {
            "bars_sha256": "bars",
            "protocol_sha256": "protocol",
            "experiment": {"initial_cash": "1000000"},
        },
    }
    if valid:
        result["metrics"] = {
            "cagr": -0.05,
            "total_return": -0.4,
            "annualized_volatility": 0.2,
            "maximum_drawdown": -0.5,
            "sharpe_ratio": -0.1,
            "turnover": 5.0,
            "total_transaction_costs": 1000.0,
        }
        table = pa.table(
            {
                "session": pa.array(["2015-01-05", "2015-01-06"]).cast(pa.date32()),
                "nav": ["1000000", "950000"],
            }
        )
        nav = destination / "nav.parquet"
        pq.write_table(table, nav)
        result["identities"]["nav_sha256"] = _sha(nav)
    else:
        result["failure"] = "synthetic missing corporate action"
    _dump(destination / "result.json", result)


def _write_content(folder: Path, value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    digest = sha256(encoded).hexdigest()
    (folder / f"{digest}.json").write_bytes(encoded)
    return digest


def _dump(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    assert isinstance(value, dict)
    return value
