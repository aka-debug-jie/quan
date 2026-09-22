from __future__ import annotations

import json
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest
from fastapi.testclient import TestClient

from quant_console.api import create_app
from quant_console.config import ConsoleConfigError, load_config
from quant_console.demo import publish_demo
from quant_console.models import CompareRequest, ExperimentFilters, SortDirection
from quant_console.repository import SnapshotRepository, SnapshotView
from quant_console.service import ConsoleService
from quant_console.snapshot import SnapshotError, build_snapshot


def _client(runtime: Path, config: Path | None = None) -> tuple[TestClient, str]:
    client = TestClient(create_app(runtime, config))
    snapshot = client.get("/api/v1/snapshot")
    assert snapshot.status_code == 200
    return client, str(snapshot.json()["snapshot_id"])


def test_demo_api_is_explicit_typed_and_safe(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    publish_demo(runtime)
    client, snapshot_id = _client(runtime)
    prefix = f"/api/v1/snapshots/{snapshot_id}"
    overview = client.get(f"{prefix}/overview")
    assert overview.json()["economic_outcome"] == "DEMO_ONLY"
    experiments = client.get(f"{prefix}/experiments?page_size=100").json()
    artifact_id = experiments["items"][0]["artifact_id"]
    detail = client.get(f"{prefix}/experiments/{artifact_id}").json()
    assert detail["data_evaluability"] == "VALID"
    assert len(detail["series"]) == 2
    series = client.get(f"{prefix}/series/{detail['series'][0]['series_id']}").json()
    assert series["points"][0]["value"] == "1000000"
    assert "absolute/" not in json.dumps(detail).lower()
    response = client.post(
        f"{prefix}/exports/experiments",
        json={
            "scope": "selected",
            "artifact_ids": [artifact_id],
            "format": "csv",
        },
    )
    assert response.status_code == 200
    assert response.content.startswith(b"\xef\xbb\xbf")
    assert response.headers["x-quant-snapshot-id"] == snapshot_id
    for endpoint in ("studies", "signals", "prospective", "health"):
        assert client.get(f"{prefix}/{endpoint}").status_code == 200
    assert client.get(f"{prefix}/experiments?sort=unsupported").status_code == 422
    evidence = client.get(f"{prefix}/evidence/evidence:demo:synthetic-run-001")
    assert evidence.json()["source_kind"] == "synthetic_fixture"
    comparison = client.post(
        f"{prefix}/comparisons/validate",
        json={"artifact_ids": [artifact_id, artifact_id]},
    )
    assert comparison.status_code == 422
    assert client.post("/api/v1/snapshot/reload").status_code == 409


def test_host_origin_and_identifiers_are_rejected_safely(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    publish_demo(runtime)
    client, snapshot_id = _client(runtime)
    assert client.get("/api/v1/snapshot", headers={"host": "evil.example"}).status_code == 400
    assert (
        client.get(
            "/api/v1/snapshot",
            headers={"origin": "https://evil.example"},
        ).status_code
        == 403
    )
    assert client.get(f"/api/v1/snapshots/{snapshot_id}/experiments/../../etc").status_code in {
        404,
        405,
    }
    unknown = client.get(f"/api/v1/snapshots/{snapshot_id}/evidence/unknown")
    assert unknown.status_code == 404
    assert str(tmp_path) not in unknown.text
    assert "x-request-id" in unknown.headers


def test_real_adapter_keeps_absolute_and_benchmark_states_separate(tmp_path: Path) -> None:
    config_path = _fixture_sources(tmp_path)
    runtime = tmp_path / "runtime"
    build_snapshot(load_config(config_path), runtime)
    client, snapshot_id = _client(runtime, config_path)
    prefix = f"/api/v1/snapshots/{snapshot_id}"
    overview = client.get(f"{prefix}/overview").json()
    assert overview["registered_runs"] == 3
    assert overview["valid_runs"] == 2
    assert overview["not_evaluable_runs"] == 1
    rows = client.get(f"{prefix}/experiments?page_size=100").json()["items"]
    candidate = next(
        item for item in rows if item["experiment_id"] == "AF7_TOP50_D20_EQ__REAL_T1_1M"
    )
    assert candidate["data_evaluability"] == "VALID"
    assert candidate["metrics"]["cagr"]["value"] == -0.05
    assert candidate["benchmark_comparability"] == "MATCHED_BENCHMARK_NOT_EVALUABLE"
    assert candidate["economic_outcome"] == "NOT_EVALUABLE"
    detail = client.get(f"{prefix}/experiments/{candidate['artifact_id']}").json()
    assert detail["benchmark_comparability"] == "MATCHED_BENCHMARK_NOT_EVALUABLE"
    assert detail["metrics"]["annualized_volatility"]["value"] == 0.2
    assert detail["metrics"]["trade_count"]["value"] == 42
    assert len(detail["series"]) == 2
    prospective = client.get(f"{prefix}/prospective").json()
    assert prospective["accounts"]["fully_prospective_v1"]["status"] == "NOT_STARTED"


def test_comparison_modes_keep_scenario_and_evaluability_boundaries(tmp_path: Path) -> None:
    config_path = _fixture_sources(tmp_path)
    runtime = tmp_path / "runtime"
    build_snapshot(load_config(config_path), runtime)
    client, snapshot_id = _client(runtime, config_path)
    prefix = f"/api/v1/snapshots/{snapshot_id}"
    rows = client.get(f"{prefix}/experiments?page_size=100").json()["items"]
    real = next(
        item
        for item in rows
        if item["scenario_id"] == "REAL_T1_1M" and item["strategy_id"].startswith("AF7")
    )
    zero = next(item for item in rows if item["scenario_id"] == "ZERO_ALL_COST_T1_1M")
    invalid = next(item for item in rows if item["data_evaluability"] == "NOT_EVALUABLE")
    controlled = client.post(
        f"{prefix}/comparisons/validate",
        json={"artifact_ids": [real["artifact_id"], zero["artifact_id"]]},
    ).json()
    assert controlled["mode"] == "CONTROLLED_SCENARIO_COMPARISON"
    assert controlled["changed_fields"] == ["cost_mode"]
    assert controlled["economic_inference_allowed"] is False
    not_evaluable = client.post(
        f"{prefix}/comparisons/validate",
        json={"artifact_ids": [real["artifact_id"], invalid["artifact_id"]]},
    ).json()
    assert not_evaluable["mode"] == "NOT_EVALUABLE"

    repository = SnapshotRepository(runtime)
    view = repository.view(snapshot_id)
    details = dict(view.details)
    zero_detail = dict(details[zero["artifact_id"]])
    compatibility = zero_detail["compatibility"]
    assert isinstance(compatibility, dict)
    zero_detail["compatibility"] = {
        **compatibility,
        "protocol_sha256": "different-protocol",
    }
    details[zero["artifact_id"]] = zero_detail

    class MismatchRepository:
        def view(self, _snapshot_id: str) -> SnapshotView:
            return replace(view, details=details)

    service = ConsoleService(cast(SnapshotRepository, MismatchRepository()))
    mismatch = service.compare(
        snapshot_id,
        CompareRequest(artifact_ids=[real["artifact_id"], zero["artifact_id"]]),
    )
    assert mismatch.mode == "DESCRIPTIVE_ONLY"
    assert "protocol_sha256 不一致" in mismatch.reasons


def test_filter_sort_and_export_apply_to_full_scope(tmp_path: Path) -> None:
    config_path = _fixture_sources(tmp_path)
    runtime = tmp_path / "runtime"
    build_snapshot(load_config(config_path), runtime)
    client, snapshot_id = _client(runtime, config_path)
    prefix = f"/api/v1/snapshots/{snapshot_id}"
    response = client.get(
        f"{prefix}/experiments",
        params={
            "q": "AF7",
            "status": "VALID",
            "sort": "cagr",
            "direction": "desc",
            "page_size": 100,
        },
    )
    assert response.status_code == 200
    assert response.json()["total"] == 2
    exported = client.post(
        f"{prefix}/exports/experiments",
        json={
            "scope": "filtered",
            "format": "json",
            "filters": {"q": "AF7", "status": "VALID"},
            "sort": "cagr",
            "direction": "desc",
        },
    )
    assert exported.status_code == 200
    payload = exported.json()
    assert payload["snapshot_id"] == snapshot_id
    assert len(payload["items"]) == 2
    assert payload["items"][0]["cagr"] == -0.05
    assert payload["items"][0]["annualized_volatility"] == 0.2
    assert payload["items"][0]["trade_count"] == 42
    assert (
        client.get(
            f"{prefix}/experiments",
            params={"sort": "benchmark_comparability", "page_size": 100},
        ).status_code
        == 200
    )
    benchmark_sorted_export = client.post(
        f"{prefix}/exports/experiments",
        json={
            "scope": "filtered",
            "format": "json",
            "filters": {"q": ""},
            "sort": "benchmark_comparability",
            "direction": "asc",
        },
    )
    assert benchmark_sorted_export.status_code == 200


def test_snapshot_identity_is_stable_and_atomic_failure_keeps_current(tmp_path: Path) -> None:
    config_path = _fixture_sources(tmp_path)
    runtime = tmp_path / "runtime"
    config = load_config(config_path)
    first = build_snapshot(config, runtime)
    first_id = SnapshotRepository(runtime).current_meta().snapshot_id
    second = build_snapshot(config, runtime)
    assert SnapshotRepository(runtime).current_meta().snapshot_id == first_id
    assert first.parent == second.parent
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
    refresh = _json(runtime / "last_refresh.json")
    assert refresh["status"] == "FAIL"
    assert refresh["reason_code"] == "SOURCE_VALIDATION_FAILED"
    assert str(tmp_path) not in json.dumps(refresh)


def test_tampered_snapshot_fails_closed_without_leaking_paths(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    publish_demo(runtime)
    repository = SnapshotRepository(runtime)
    snapshot_id = repository.current_meta().snapshot_id
    overview = runtime / "snapshots" / snapshot_id / "overview.json"
    overview.write_text("{}", encoding="utf-8")
    client = TestClient(create_app(runtime))
    response = client.get(f"/api/v1/snapshots/{snapshot_id}/overview")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SNAPSHOT_INVALID"
    assert str(tmp_path) not in response.text


def test_config_rejects_demo_missing_and_sealed_sources(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("mode='demo'\n", encoding="utf-8")
    with pytest.raises(ConsoleConfigError):
        load_config(path)
    sealed = tmp_path / "sealed"
    sealed.mkdir()
    manifest = sealed / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    config = tmp_path / "sealed.toml"
    config.write_text(
        "\n".join(
            (
                'mode = "real"',
                "[historical_v3]",
                f'manifest = "{manifest}"',
                f'artifacts = "{sealed}"',
                "[upgrade_v1]",
                f'manifest = "{manifest}"',
                f'artifacts = "{sealed}"',
                "[prospective]",
                f'artifacts = "{sealed}"',
                f'acceptance_manifest = "{manifest}"',
            )
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConsoleConfigError, match="sealed"):
        load_config(config)


def test_openapi_has_typed_models_without_reading_data(tmp_path: Path) -> None:
    app = create_app(tmp_path / "missing")
    schema = app.openapi()
    assert "SnapshotMeta" in schema["components"]["schemas"]
    operation = schema["paths"]["/api/v1/snapshots/{snapshot_id}/experiments"]["get"]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"]


def test_client_side_scale_contract_covers_ten_thousand_rows(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    publish_demo(runtime)
    repository = SnapshotRepository(runtime)
    base = repository.view(repository.current_meta().snapshot_id)
    template = base.experiments[0]
    rows = []
    for index in range(10_000):
        row = dict(template)
        row["artifact_id"] = f"demo:scale:{index:05d}"
        row["experiment_id"] = f"SCALE_{index:05d}"
        row["run_identity"] = f"{index:064x}"
        rows.append(row)

    class ScaleRepository:
        def view(self, _snapshot_id: str) -> SnapshotView:
            return replace(base, experiments=rows)

    service = ConsoleService(cast(SnapshotRepository, ScaleRepository()))
    result = service.experiments(
        base.meta.snapshot_id,
        filters=ExperimentFilters(q="SCALE_"),
        page=1,
        page_size=10_000,
        sort="experiment_id",
        direction=SortDirection.DESC,
    )
    assert result.total == 10_000
    assert len(result.items) == 10_000
    assert result.items[0].experiment_id == "SCALE_09999"


def test_web_modules_do_not_import_runners_brokers_providers_or_system_commands() -> None:
    package = Path(__file__).parents[1] / "src" / "quant_console"
    text = "\n".join(
        (package / name).read_text(encoding="utf-8")
        for name in (
            "api.py",
            "repository.py",
            "service.py",
            "snapshot.py",
            "config.py",
            "models.py",
        )
    )
    for forbidden in (
        "prospective_runner",
        "paper_broker",
        "akshare",
        "requests",
        "sqlite3",
        "systemctl",
        "subprocess",
    ):
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
    candidate_id, zero_id, benchmark_id = "2" * 64, "4" * 64, "3" * 64
    _write_run(upgrade_artifacts, candidate_id, "AF7_TOP50_D20_EQ", "REAL_T1_1M", valid=True)
    _write_run(
        upgrade_artifacts,
        zero_id,
        "AF7_TOP50_D20_EQ",
        "ZERO_ALL_COST_T1_1M",
        valid=True,
    )
    _write_run(upgrade_artifacts, benchmark_id, "B50_LIQ50_D20", "REAL_T1_1M", valid=False)
    upgrade_matrix = {
        "schema_version": 1,
        "status": "COMPLETE",
        "candidate_outcomes": {"AF7_TOP50_D20_EQ": "NOT_EVALUABLE"},
        "result_identities": {
            "AF7_TOP50_D20_EQ__REAL_T1_1M": candidate_id,
            "AF7_TOP50_D20_EQ__ZERO_ALL_COST_T1_1M": zero_id,
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
    cost_mode = "zero_all" if scenario.startswith("ZERO_ALL") else "real"
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
            "base_protocol_sha256": "base-protocol",
            "portfolio_sha256": "portfolio",
            "scores_sha256": "scores",
            "signals_sha256": "signals",
            "experiment": {
                "initial_cash": "1000000",
                "cost_mode": cost_mode,
                "execution_delay_sessions": 1,
            },
        },
    }
    if valid:
        result["execution"] = {"fills": 42}
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
