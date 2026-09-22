"""Content-addressed read-only view construction for real research artifacts."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from quant_console.config import ConsoleConfig

JSON = dict[str, Any]
ADAPTER_VERSION = "quant-console-v1.5"
SNAPSHOT_SCHEMA_VERSION = 2


class SnapshotError(ValueError):
    """Raised when one approved source cannot be represented safely."""


def build_snapshot(config: ConsoleConfig, runtime: Path, observation: Path | None = None) -> Path:
    """Build and atomically publish a coherent application snapshot."""
    try:
        v3 = _load_study(
            "historical_v3", config.historical_v3.manifest, config.historical_v3.artifacts
        )
        upgrade = _load_study(
            "quant_upgrade_v1", config.upgrade_v1.manifest, config.upgrade_v1.artifacts
        )
        prospective = _load_prospective(config.prospective_artifacts, config.prospective_acceptance)
        prospective_public = {
            key: value for key, value in prospective.items() if key not in {"evidence", "health"}
        }
        system = _load_observation(observation)
        experiments = cast(list[JSON], v3["experiments"]) + cast(list[JSON], upgrade["experiments"])
        details = cast(JSON, v3["details"]) | cast(JSON, upgrade["details"])
        evidence = cast(JSON, v3["evidence"]) | cast(JSON, upgrade["evidence"])
        registered = int(upgrade["registered_runs"])
        valid = sum(
            item["data_evaluability"] == "VALID"
            for item in cast(list[JSON], upgrade["experiments"])
        )
        not_evaluable = registered - valid
        body: JSON = {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "mode": "real",
            "overview": {
                "current_stage": "CN_QUANT_RESEARCH_UPGRADE_V1_COMPLETE",
                "registered_runs": registered,
                "valid_runs": valid,
                "not_evaluable_runs": not_evaluable,
                "retained_candidates": int(upgrade["retained_candidates"]),
                "legacy_invalid_engineering_runs": int(upgrade["legacy_count"]),
                "economic_outcome": upgrade["economic_outcome"],
                "latest_prospective_date": prospective.get("latest_date"),
                "prospective_status": prospective.get("operations_status"),
                "warnings": prospective.get("warnings", []),
            },
            "studies": [v3["study"], upgrade["study"]],
            "experiments": experiments,
            "experiment_details": details,
            "signals": {
                "historical": v3.get("signals", {}),
                "attribution": upgrade.get("attribution", {}),
                "measurement": upgrade.get("measurement", {}),
                "prospective": prospective.get("diagnostics", {}),
            },
            "prospective": prospective_public,
            "health": {
                "sources": [v3["health"], upgrade["health"], prospective["health"]],
                "system_observation": system,
                "live_broker": "FORBIDDEN",
                "csi500": "NOT_READ",
            },
            "evidence": evidence | cast(JSON, prospective.get("evidence", {})),
        }
        return publish_read_model(body, runtime)
    except Exception as error:
        _atomic_json(
            runtime / "last_refresh.json",
            {"status": "FAIL", "observed_at": datetime.now(UTC).isoformat(), "reason": str(error)},
        )
        raise


def load_current(runtime: Path) -> JSON:
    """Load the current snapshot manifest without touching source artifacts."""
    pointer = _json_object(runtime / "current.json")
    snapshot_id = str(pointer["snapshot_id"])
    _validate_digest(snapshot_id)
    return _json_object(runtime / "snapshots" / snapshot_id / "manifest.json")


def _load_study(study_id: str, manifest_path: Path, artifacts: Path) -> JSON:
    manifest = _json_object(manifest_path)
    manifest_sha = _file_sha256(manifest_path)
    study_revision = manifest_sha
    matrix_sha = str(manifest["matrix_sha256"])
    matrix_path = _within(artifacts, Path("matrix") / f"{matrix_sha}.json")
    _require_hash(matrix_path, matrix_sha)
    matrix = _json_object(matrix_path)
    identities = matrix.get("result_identities")
    if not isinstance(identities, dict):
        raise SnapshotError(f"{study_id}: result identities missing")
    experiments: list[JSON] = []
    details: JSON = {}
    evidence: JSON = {}
    for experiment_id, run_identity_value in sorted(identities.items()):
        run_identity = str(run_identity_value)
        result_path = _within(artifacts, Path("runs") / run_identity / "result.json")
        result = _json_object(result_path)
        if str(result.get("run_identity", run_identity)) != run_identity:
            raise SnapshotError(f"{study_id}: run identity mismatch")
        artifact_id = f"{study_id}:{run_identity}"
        summary, detail = _normalize_run(
            study_id,
            study_revision,
            str(experiment_id),
            run_identity,
            result,
            result_path,
        )
        nav_path = result_path.parent / "nav.parquet"
        if summary["data_evaluability"] == "VALID" and nav_path.exists():
            expected = cast(JSON, result.get("identities", {})).get("nav_sha256")
            if expected:
                _require_hash(nav_path, str(expected))
            detail["nav_series"] = _nav_series(nav_path)
            if detail["nav_series"]:
                detail["period"] = {
                    "start": detail["nav_series"][0]["date"],
                    "end": detail["nav_series"][-1]["date"],
                    "sessions": len(detail["nav_series"]),
                }
                summary["period"] = detail["period"]
        else:
            detail["nav_series"] = None
            detail["curve_unavailable_reason"] = "运行不可评价或不存在经校验的净值序列"
        source_sha = _file_sha256(result_path)
        evidence_id = f"evidence:{study_id}:{run_identity}"
        summary["artifact_id"] = artifact_id
        summary["evidence_id"] = evidence_id
        detail["artifact_id"] = artifact_id
        detail["evidence_id"] = evidence_id
        for metric_name, metric_value in cast(JSON, summary["metrics"]).items():
            metric = cast(JSON, metric_value)
            metric.update(
                {
                    "name": metric_name,
                    "basis": "source_reported_full_period",
                    "scenario_id": summary["scenario_id"],
                    "data_use_level": summary["data_use_level"],
                    "source_evidence_id": evidence_id,
                }
            )
        detail["metrics"] = summary["metrics"]
        summary.pop("compatibility", None)
        experiments.append(summary)
        details[artifact_id] = detail
        evidence[evidence_id] = {
            "source_kind": "run_result",
            "study_id": study_id,
            "study_revision": study_revision,
            "run_identity": run_identity,
            "sha256": source_sha,
            "schema_version": result.get("schema_version"),
            "data_use_level": result.get("DATA_USE_LEVEL"),
            "limitations": result.get("limitations") or [],
        }
    _attach_benchmark_states(study_id, experiments, matrix)
    for summary in experiments:
        detail = cast(JSON, details[str(summary["artifact_id"])])
        for field in (
            "benchmark_comparability",
            "economic_outcome",
            "matched_benchmark_id",
        ):
            if field in summary:
                detail[field] = summary[field]
    legacy_count = 0
    if study_id == "quant_upgrade_v1":
        all_results = list((artifacts / "runs").glob("*/result.json"))
        legacy_count = len(all_results) - len(identities)
        expected_legacy = int(manifest.get("invalid_engineering_prefixed_runs_retained", 0))
        if legacy_count != expected_legacy:
            raise SnapshotError("upgrade legacy artifact count conflicts with manifest")
    signals: JSON = {}
    attribution: JSON = {}
    measurement: JSON = {}
    if study_id == "historical_v3":
        diagnostic_sha = str(manifest["signal_diagnostics_sha256"])
        diagnostic_path = _within(artifacts, Path("diagnostics") / f"{diagnostic_sha}.json")
        _require_hash(diagnostic_path, diagnostic_sha)
        signals = _json_object(diagnostic_path)
    else:
        attribution = _manifest_artifact(
            manifest, artifacts, "signal_attribution_sha256", "attribution"
        )
        measurement = _manifest_artifact(
            manifest, artifacts, "measurement_audit_sha256", "measurement"
        )
    retained = int(manifest.get("retained_candidates", 0))
    return {
        "study": {
            "study_id": study_id,
            "study_revision": study_revision,
            "schema_version": manifest.get("schema_version"),
            "code_commit": manifest.get("validated_code_commit"),
            "implementation_status": manifest.get("IMPLEMENTATION_STATUS"),
            "research_validity": manifest.get("RESEARCH_VALIDITY"),
            "economic_outcome": manifest.get("ECONOMIC_OUTCOME"),
            "data_use_level": manifest.get("DATA_USE_LEVEL"),
            "registered_runs": len(identities),
        },
        "experiments": experiments,
        "details": details,
        "evidence": evidence,
        "registered_runs": len(identities),
        "retained_candidates": retained,
        "legacy_count": legacy_count,
        "economic_outcome": manifest.get("ECONOMIC_OUTCOME"),
        "signals": signals,
        "attribution": attribution,
        "measurement": measurement,
        "health": {
            "source_id": study_id,
            "verification_status": "HASH_VERIFIED",
            "manifest_sha256": manifest_sha,
            "matrix_sha256": matrix_sha,
        },
    }


def _normalize_run(
    study_id: str,
    study_revision: str,
    experiment_id: str,
    run_identity: str,
    result: JSON,
    result_path: Path,
) -> tuple[JSON, JSON]:
    metrics = result.get("metrics")
    valid = isinstance(metrics, dict)
    data_status = "VALID" if valid else "NOT_EVALUABLE"
    scenario = str(result.get("scenario_id", "BASE"))
    strategy = str(result.get("strategy_id", experiment_id.split("__", maxsplit=1)[0]))
    summary: JSON = {
        "study_id": study_id,
        "study_revision": study_revision,
        "experiment_id": experiment_id,
        "run_identity": run_identity,
        "strategy_id": strategy,
        "family": _family(strategy),
        "scenario_id": scenario,
        "data_evaluability": data_status,
        "benchmark_comparability": "NOT_APPLICABLE",
        "economic_outcome": "NOT_TESTED" if study_id == "historical_v3" else "NOT_EVALUABLE",
        "engineering_status": str(result.get("IMPLEMENTATION_STATUS", "UNKNOWN")),
        "research_validity": str(result.get("RESEARCH_VALIDITY", "UNKNOWN")),
        "data_use_level": str(result.get("DATA_USE_LEVEL", "UNKNOWN")),
        "metrics": _metric_map(cast(JSON, metrics) if valid else {}),
        "failure_reason": None if valid else _failure_reason(result),
        "period": None,
        "compatibility": {
            "study_revision": study_revision,
            "scenario_id": scenario,
            "bars_sha256": cast(JSON, result.get("identities", {})).get("bars_sha256"),
            "protocol_sha256": cast(JSON, result.get("identities", {})).get(
                "upgrade_protocol_sha256"
            )
            or cast(JSON, result.get("identities", {})).get("protocol_sha256"),
            "base_protocol_sha256": cast(JSON, result.get("identities", {})).get(
                "base_protocol_sha256"
            ),
            "portfolio_sha256": cast(JSON, result.get("identities", {})).get("portfolio_sha256"),
            "scores_sha256": cast(JSON, result.get("identities", {})).get("scores_sha256"),
            "signals_sha256": cast(JSON, result.get("identities", {})).get("signals_sha256"),
            "initial_cash": cast(
                JSON, cast(JSON, result.get("identities", {})).get("experiment", {})
            ).get("initial_cash"),
            "cost_mode": cast(
                JSON, cast(JSON, result.get("identities", {})).get("experiment", {})
            ).get("cost_mode"),
            "execution_delay_sessions": cast(
                JSON, cast(JSON, result.get("identities", {})).get("experiment", {})
            ).get("execution_delay_sessions"),
        },
    }
    detail = dict(summary)
    detail.update(
        {
            "execution": result.get("execution"),
            "turnover_costs": result.get("turnover_costs"),
            "calendar_year_returns": result.get("calendar_year_returns"),
            "identities": result.get("identities"),
            "limitations": result.get("limitations") or [],
            "source_sha256": _file_sha256(result_path),
            "series": [],
            "curve_unavailable_reason": None,
        }
    )
    return summary, detail


def _attach_benchmark_states(study_id: str, experiments: list[JSON], matrix: JSON) -> None:
    by_name = {str(item["experiment_id"]): item for item in experiments}
    if study_id == "historical_v3":
        benchmark_strategy = str(matrix.get("benchmark_id", ""))
        for item in experiments:
            if item["strategy_id"] == benchmark_strategy:
                item["benchmark_comparability"] = "SELF_BENCHMARK"
                item["economic_outcome"] = "REFERENCE"
            else:
                item["benchmark_comparability"] = "COMPARABLE"
                item["economic_outcome"] = str(matrix.get("ECONOMIC_OUTCOME", "UNKNOWN"))
        return
    outcomes = cast(JSON, matrix.get("candidate_outcomes", {}))
    benchmark_for = {
        "AF7_LOW_AVOID100_D20": "B100_LIQ100_D20",
        "AF7_TOP50_D20_EQ": "B50_LIQ50_D20",
        "AF7_TOP50_D20_HOLD100_BAND25": "B50_LIQ50_D20",
        "AF7_TOP50_D5_STEP25": "B50_LIQ50_D20",
        "CONDREV5_TOP50_D20_EQ": "B50_LIQ50_D20",
        "DOWN60_TOP50_D20_EQ": "B50_LIQ50_D20",
        "MOM605_TOP50_D20_EQ": "B50_LIQ50_D20",
        "ROBUSTTREND_TOP50_D20_EQ": "B50_LIQ50_D20",
    }
    for item in experiments:
        strategy = str(item["strategy_id"])
        if strategy in benchmark_for:
            benchmark_id = f"{benchmark_for[strategy]}__{item['scenario_id']}"
            benchmark_row = by_name.get(benchmark_id)
            item["matched_benchmark_id"] = benchmark_id
            if benchmark_row is None:
                item["benchmark_comparability"] = "MATCHED_BENCHMARK_MISSING"
            elif benchmark_row["data_evaluability"] == "VALID":
                item["benchmark_comparability"] = "COMPARABLE"
            else:
                item["benchmark_comparability"] = "MATCHED_BENCHMARK_NOT_EVALUABLE"
            item["economic_outcome"] = str(outcomes.get(strategy, "NOT_EVALUABLE"))
        elif strategy.startswith("B"):
            item["benchmark_comparability"] = "SELF_BENCHMARK"
            item["economic_outcome"] = "REFERENCE"
        else:
            item["benchmark_comparability"] = "NOT_APPLICABLE"
            item["economic_outcome"] = "DIAGNOSTIC_ONLY"


def _load_prospective(root: Path, acceptance_path: Path) -> JSON:
    root = root.resolve(strict=True)
    acceptance = _json_object(acceptance_path)
    selected: dict[str, tuple[int, str, JSON]] = {}
    evidence: JSON = {}
    for path in sorted((root / "daily").glob("*.json")):
        path = _within(root, path.relative_to(root))
        payload = _json_object(path)
        date_value = str(payload.get("trading_date", ""))
        if not date_value:
            continue
        suffix = path.stem.split("-", maxsplit=3)[-1]
        if len(suffix) == 64:
            _require_hash(path, suffix)
        key = (int(payload.get("schema_version", 0)), path.name, payload)
        if date_value not in selected or key[:2] > selected[date_value][:2]:
            selected[date_value] = key
    days = [item[2] for _, item in sorted(selected.items())]
    latest = days[-1] if days else {}
    diagnostics: JSON = {}
    diagnostics_files = sorted((root / "diagnostics").glob("*.json"))
    if diagnostics_files:
        diagnostics = _json_object(diagnostics_files[-1])
    formal = [day for day in days if day.get("paper_account_phase") == "fully_prospective_v1"]
    engineering = [
        day for day in days if day.get("paper_account_phase") == "engineering_warm_start"
    ]
    warnings: list[str] = []
    if latest.get("DATA_CAPTURE_STATUS") not in (None, "COMPLETE"):
        warnings.append(str(latest.get("DATA_CAPTURE_STATUS")))
    if latest.get("INPUT_STATUS") != "FULLY_PROSPECTIVE_INPUT":
        warnings.append(str(latest.get("INPUT_STATUS", "INPUT_STATUS_UNKNOWN")))
    evidence_id = "evidence:prospective:latest"
    evidence[evidence_id] = {
        "source_kind": "published_daily_json",
        "trading_date": latest.get("trading_date"),
        "receipt_sha256": latest.get("receipt_sha256"),
        "rules_sha256": latest.get("rules_sha256"),
        "calendar_sha256": latest.get("calendar_sha256"),
        "absolute_paths_exposed": False,
    }
    public_days = [_sanitize_prospective(day) for day in days]
    return {
        "latest_date": latest.get("trading_date"),
        "operations_status": latest.get(
            "OPERATIONS_ACCEPTANCE_STATUS", acceptance.get("acceptance_status", "UNKNOWN")
        ),
        "input_status": latest.get("INPUT_STATUS", "UNKNOWN"),
        "data_capture_status": latest.get("DATA_CAPTURE_STATUS", "UNKNOWN"),
        "profitability_status": latest.get("PROFITABILITY_STATUS", "UNKNOWN"),
        "days": public_days,
        "accounts": {
            "engineering_warm_start": _account_summary(engineering),
            "fully_prospective_v1": _account_summary(formal),
        },
        "diagnostics": diagnostics,
        "warnings": warnings,
        "evidence_id": evidence_id,
        "evidence": evidence,
        "health": {
            "source_id": "prospective_rc02",
            "verification_status": "PUBLISHED_JSON_ONLY",
            "latest_report_date": latest.get("trading_date"),
            "acceptance_status": acceptance.get("acceptance_status"),
            "sqlite_read": False,
        },
    }


def _sanitize_prospective(value: JSON) -> JSON:
    allowed = (
        "trading_date",
        "ENGINEERING_STATUS",
        "INPUT_STATUS",
        "DATA_CAPTURE_STATUS",
        "SHADOW_SIGNAL_STATUS",
        "PAPER_ACCOUNT_STATUS",
        "paper_account_phase",
        "PROFITABILITY_STATUS",
        "coverage",
        "nav",
        "cash",
        "fills_today",
        "buy_fills_today",
        "sell_fills_today",
        "rejections_today",
        "mean_ic",
        "mean_rank_ic",
        "direction_consistency",
        "receipt_sha256",
        "rules_sha256",
        "calendar_sha256",
    )
    output = {key: value.get(key) for key in allowed}
    output["top_count"] = len(cast(list[Any], value.get("top", [])))
    output["position_count"] = len(cast(list[Any], value.get("positions", [])))
    output["rejection_count"] = len(cast(list[Any], value.get("rejections_today", [])))
    output.pop("rejections_today", None)
    return output


def _account_summary(days: list[JSON]) -> JSON:
    if not days:
        return {"status": "NOT_STARTED", "latest": None}
    latest = _sanitize_prospective(days[-1])
    return {"status": "OBSERVED", "latest": latest, "observed_days": len(days)}


def _load_observation(path: Path | None) -> JSON:
    if path is None or not path.exists():
        return {"status": "CURRENT_UNKNOWN", "observed_at": None}
    value = _json_object(path)
    return {
        "status": value.get("status", "OBSERVED"),
        "observed_at": value.get("observed_at"),
        "timer": value.get("timer"),
        "service": value.get("service"),
        "unit_hashes": value.get("unit_hashes"),
    }


def _manifest_artifact(manifest: JSON, root: Path, key: str, folder: str) -> JSON:
    digest = str(manifest[key])
    path = _within(root, Path(folder) / f"{digest}.json")
    _require_hash(path, digest)
    return _json_object(path)


def _nav_series(path: Path) -> list[JSON]:
    table = pq.read_table(path, columns=["session", "nav"])
    return [
        {"date": row["session"].isoformat(), "nav": str(row["nav"])} for row in table.to_pylist()
    ]


def _metric_map(metrics: JSON) -> JSON:
    units = {
        "cagr": "ratio",
        "total_return": "ratio",
        "annualized_volatility": "ratio",
        "maximum_drawdown": "ratio",
        "sharpe_ratio": "ratio",
        "turnover": "two_sided_ratio",
        "total_transaction_costs": "CNY",
    }
    return {
        key: {
            "value": metrics.get(key),
            "unit": unit,
            "validity": "VALID" if key in metrics else "NOT_AVAILABLE",
            "unavailable_reason": None if key in metrics else "source metric unavailable",
        }
        for key, unit in units.items()
    }


def publish_read_model(body: JSON, runtime: Path) -> Path:
    """Publish a split, content-addressed read model and atomically move current."""
    runtime.mkdir(parents=True, exist_ok=True)
    snapshots = runtime / "snapshots"
    snapshots.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".snapshot-", dir=snapshots))
    published_at = datetime.now(UTC).isoformat()
    try:
        experiments = cast(list[JSON], body["experiments"])
        details = cast(JSON, body["experiment_details"])
        series_dir = temporary / "series"
        series_dir.mkdir()
        for _artifact_id, raw_detail in details.items():
            detail = cast(JSON, raw_detail)
            nav = detail.pop("nav_series", None)
            if isinstance(nav, list) and nav:
                series = _publish_series(series_dir, cast(list[JSON], nav), detail)
                detail["series"] = series
            else:
                detail["series"] = []
                detail.setdefault(
                    "curve_unavailable_reason",
                    "运行不可评价或不存在经校验的净值序列",
                )
        parts: dict[str, object] = {
            "overview.json": body["overview"],
            "studies.json": body["studies"],
            "experiments.json": experiments,
            "details.json": details,
            "signals.json": body["signals"],
            "prospective.json": body["prospective"],
            "health.json": body["health"],
            "evidence.json": body["evidence"],
        }
        for name, value in parts.items():
            (temporary / name).write_bytes(_canonical(value))
        _write_ledger(temporary / "ledger.parquet", experiments)
        file_hashes = {
            str(path.relative_to(temporary)): _file_sha256(path)
            for path in sorted(temporary.rglob("*"))
            if path.is_file()
        }
        identity = {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "adapter_version": ADAPTER_VERSION,
            "mode": body["mode"],
            "files": file_hashes,
        }
        snapshot_id = sha256(_canonical(identity)).hexdigest()
        manifest: JSON = {
            **identity,
            "snapshot_id": snapshot_id,
            "published_at": published_at,
        }
        (temporary / "manifest.json").write_bytes(_canonical(manifest))
        destination = snapshots / snapshot_id
        if destination.exists():
            shutil.rmtree(temporary)
        else:
            temporary.replace(destination)
        _atomic_json(
            runtime / "current.json",
            {"snapshot_id": snapshot_id, "published_at": published_at},
        )
        _atomic_json(
            runtime / "last_refresh.json",
            {
                "status": "PASS",
                "observed_at": published_at,
                "snapshot_id": snapshot_id,
            },
        )
        return destination / "manifest.json"
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def _publish_series(series_dir: Path, nav: list[JSON], detail: JSON) -> list[JSON]:
    nav_points = [{"date": str(row["date"]), "value": str(row["nav"])} for row in nav]
    identities = cast(JSON, detail.get("identities", {}))
    source_sha = str(
        identities.get("nav_sha256") or sha256(_canonical_list(nav_points)).hexdigest()
    )
    nav_meta = _series_file(
        series_dir,
        kind="NAV",
        unit="CNY",
        points=nav_points,
        source_sha=source_sha,
        derivation="SOURCE_NAV_FULL_PRECISION",
    )
    peak: Decimal | None = None
    drawdown_points: list[JSON] = []
    for point in nav_points:
        value = Decimal(str(point["value"]))
        peak = value if peak is None or value > peak else peak
        drawdown = Decimal(0) if peak == 0 else value / peak - Decimal(1)
        drawdown_points.append({"date": point["date"], "value": format(drawdown, "f")})
    drawdown_meta = _series_file(
        series_dir,
        kind="DRAWDOWN",
        unit="ratio",
        points=drawdown_points,
        source_sha=source_sha,
        derivation="RUNNING_PEAK_DRAWDOWN_V1",
    )
    return [nav_meta, drawdown_meta]


def _series_file(
    series_dir: Path,
    *,
    kind: str,
    unit: str,
    points: list[JSON],
    source_sha: str,
    derivation: str,
) -> JSON:
    content: JSON = {
        "kind": kind,
        "unit": unit,
        "start": points[0]["date"],
        "end": points[-1]["date"],
        "points": points,
        "source_sha256": source_sha,
        "derivation": derivation,
    }
    series_id = sha256(_canonical(content)).hexdigest()
    meta: JSON = {
        "series_id": series_id,
        "kind": kind,
        "unit": unit,
        "start": content["start"],
        "end": content["end"],
        "points": len(points),
        "source_sha256": source_sha,
        "derivation": derivation,
    }
    (series_dir / f"{series_id}.json").write_bytes(_canonical({"meta": meta, "points": points}))
    return meta


def _write_ledger(path: Path, experiments: list[JSON]) -> None:
    rows: list[JSON] = []
    metric_names = (
        "cagr",
        "total_return",
        "annualized_volatility",
        "maximum_drawdown",
        "sharpe_ratio",
        "turnover",
        "total_transaction_costs",
    )
    for item in experiments:
        metrics = cast(JSON, item.get("metrics", {}))
        period = cast(JSON, item.get("period") or {})
        row: JSON = {
            key: item.get(key)
            for key in (
                "artifact_id",
                "evidence_id",
                "study_id",
                "study_revision",
                "experiment_id",
                "run_identity",
                "strategy_id",
                "family",
                "scenario_id",
                "data_evaluability",
                "benchmark_comparability",
                "economic_outcome",
                "engineering_status",
                "research_validity",
                "data_use_level",
                "failure_reason",
                "matched_benchmark_id",
                "revision_of",
            )
        }
        row.update(
            {
                "period_start": period.get("start"),
                "period_end": period.get("end"),
                "period_sessions": period.get("sessions"),
            }
        )
        for metric_name in metric_names:
            metric = cast(JSON, metrics.get(metric_name, {}))
            row[metric_name] = metric.get("value")
        rows.append(row)
    pq.write_table(pa.Table.from_pylist(rows), path, compression="zstd")


def _canonical_list(value: list[JSON]) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def _failure_reason(result: JSON) -> str:
    for key in ("failure", "reason", "error"):
        if isinstance(result.get(key), str):
            return str(result[key])
    return str(result.get("RESEARCH_VALIDITY", "not evaluable"))


def _family(strategy: str) -> str:
    if strategy.startswith("AF7") or strategy.startswith("A0"):
        return "AF7"
    if strategy.startswith("B"):
        return "BENCHMARK"
    if "CONDREV" in strategy:
        return "CONDITIONAL_REVERSAL"
    if "MOM" in strategy:
        return "MOMENTUM"
    if "DOWN" in strategy:
        return "DOWNSIDE_RISK"
    if "ROBUST" in strategy:
        return "ROBUST_TREND"
    return "OTHER"


def _json_object(path: Path) -> JSON:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as error:
        raise SnapshotError(f"cannot read structured source: {path.name}: {error}") from error
    if not isinstance(value, dict):
        raise SnapshotError(f"structured source must be an object: {path.name}")
    return cast(JSON, value)


def _within(root: Path, relative: Path) -> Path:
    resolved_root = root.resolve(strict=True)
    candidate = (resolved_root / relative).resolve(strict=True)
    if not candidate.is_relative_to(resolved_root):
        raise SnapshotError("source path escapes approved root")
    if not candidate.is_file():
        raise SnapshotError("approved source is not a regular file")
    return candidate


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _require_hash(path: Path, expected: str) -> None:
    if _file_sha256(path) != expected:
        raise SnapshotError(f"hash mismatch for approved source: {path.name}")


def _validate_digest(value: str) -> None:
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise SnapshotError("invalid snapshot identity")


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def _atomic_json(path: Path, value: JSON) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(_canonical(value))
            handle.flush()
            os.fsync(handle.fileno())
        Path(temporary_name).replace(path)
    finally:
        Path(temporary_name).unlink(missing_ok=True)
