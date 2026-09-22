"""Content-addressed read-only view construction for real research artifacts."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

import pyarrow.parquet as pq  # type: ignore[import-untyped]

from quant_console.config import ConsoleConfig

JSON = dict[str, Any]


class SnapshotError(ValueError):
    """Raised when one approved source cannot be represented safely."""


def build_snapshot(config: ConsoleConfig, runtime: Path, observation: Path | None = None) -> Path:
    """Build and atomically publish a coherent application snapshot."""
    runtime.mkdir(parents=True, exist_ok=True)
    snapshots = runtime / "snapshots"
    snapshots.mkdir(parents=True, exist_ok=True)
    try:
        v3 = _load_study(
            "historical_v3", config.historical_v3.manifest, config.historical_v3.artifacts
        )
        upgrade = _load_study(
            "quant_upgrade_v1", config.upgrade_v1.manifest, config.upgrade_v1.artifacts
        )
        prospective = _load_prospective(config.prospective_artifacts, config.prospective_acceptance)
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
            "schema_version": 1,
            "generated_at": datetime.now(UTC).isoformat(),
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
            "prospective": prospective,
            "health": {
                "sources": [v3["health"], upgrade["health"], prospective["health"]],
                "system_observation": system,
                "live_broker": "FORBIDDEN",
                "csi500": "NOT_READ",
            },
            "evidence": evidence | cast(JSON, prospective.get("evidence", {})),
        }
        encoded_without_id = _canonical(body)
        snapshot_id = sha256(encoded_without_id).hexdigest()
        body["snapshot_id"] = snapshot_id
        encoded = _canonical(body)
        temporary = Path(tempfile.mkdtemp(prefix=".snapshot-", dir=snapshots))
        try:
            (temporary / "snapshot.json").write_bytes(encoded)
            destination = snapshots / snapshot_id
            if destination.exists():
                shutil.rmtree(temporary)
            else:
                temporary.replace(destination)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
        _atomic_json(runtime / "current.json", {"snapshot_id": snapshot_id})
        _atomic_json(
            runtime / "last_refresh.json",
            {
                "status": "PASS",
                "observed_at": datetime.now(UTC).isoformat(),
                "snapshot_id": snapshot_id,
            },
        )
        return snapshots / snapshot_id / "snapshot.json"
    except Exception as error:
        _atomic_json(
            runtime / "last_refresh.json",
            {"status": "FAIL", "observed_at": datetime.now(UTC).isoformat(), "reason": str(error)},
        )
        raise


def load_current(runtime: Path) -> JSON:
    """Load the current immutable snapshot without touching source artifacts."""
    pointer = _json_object(runtime / "current.json")
    snapshot_id = str(pointer["snapshot_id"])
    if len(snapshot_id) != 64 or any(ch not in "0123456789abcdef" for ch in snapshot_id):
        raise SnapshotError("invalid current snapshot identity")
    return _json_object(runtime / "snapshots" / snapshot_id / "snapshot.json")


def _load_study(study_id: str, manifest_path: Path, artifacts: Path) -> JSON:
    manifest = _json_object(manifest_path)
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
            study_id, str(experiment_id), run_identity, result, result_path
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
        experiments.append(summary)
        details[artifact_id] = detail
        evidence[evidence_id] = {
            "source_kind": "run_result",
            "study_id": study_id,
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
            "manifest_sha256": _file_sha256(manifest_path),
            "matrix_sha256": matrix_sha,
        },
    }


def _normalize_run(
    study_id: str, experiment_id: str, run_identity: str, result: JSON, result_path: Path
) -> tuple[JSON, JSON]:
    metrics = result.get("metrics")
    valid = isinstance(metrics, dict)
    data_status = "VALID" if valid else "NOT_EVALUABLE"
    scenario = str(result.get("scenario_id", "BASE"))
    strategy = str(result.get("strategy_id", experiment_id.split("__", maxsplit=1)[0]))
    summary: JSON = {
        "study_id": study_id,
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
            "study_revision": study_id,
            "scenario_id": scenario,
            "bars_sha256": cast(JSON, result.get("identities", {})).get("bars_sha256"),
            "protocol_sha256": cast(JSON, result.get("identities", {})).get(
                "upgrade_protocol_sha256"
            )
            or cast(JSON, result.get("identities", {})).get("protocol_sha256"),
            "initial_cash": cast(
                JSON, cast(JSON, result.get("identities", {})).get("experiment", {})
            ).get("initial_cash"),
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
            "source": {
                "kind": "structured_json",
                "sha256": _file_sha256(result_path),
                "path_exposed": False,
            },
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


def _canonical(value: JSON) -> bytes:
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
