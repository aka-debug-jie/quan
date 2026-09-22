"""Explicit synthetic snapshot for CI and demonstration mode."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any


def _metric(value: float, unit: str) -> dict[str, Any]:
    return {
        "value": value,
        "unit": unit,
        "validity": "VALID",
        "unavailable_reason": None,
    }


def publish_demo(runtime: Path) -> Path:
    """Publish a small, visibly synthetic snapshot."""
    experiment: dict[str, Any] = {
        "artifact_id": "demo:synthetic-run-001",
        "evidence_id": "evidence:demo:synthetic-run-001",
        "study_id": "demo_study",
        "experiment_id": "SYNTHETIC_A",
        "run_identity": "synthetic-run-001",
        "strategy_id": "SYNTHETIC_A",
        "family": "DEMO",
        "scenario_id": "DEMO_T1",
        "data_evaluability": "VALID",
        "benchmark_comparability": "COMPARABLE",
        "economic_outcome": "DEMO_ONLY",
        "engineering_status": "DEMO_ONLY",
        "research_validity": "SYNTHETIC_NOT_RESEARCH",
        "data_use_level": "SYNTHETIC",
        "metrics": {
            "cagr": _metric(-0.03, "ratio"),
            "total_return": _metric(-0.08, "ratio"),
            "annualized_volatility": _metric(0.18, "ratio"),
            "maximum_drawdown": _metric(-0.15, "ratio"),
            "sharpe_ratio": _metric(-0.1, "ratio"),
            "turnover": _metric(3.0, "two_sided_ratio"),
            "total_transaction_costs": _metric(1234.5, "CNY"),
        },
        "failure_reason": None,
        "period": {"start": "2025-01-02", "end": "2025-01-06", "sessions": 3},
        "compatibility": {
            "study_revision": "demo_study",
            "scenario_id": "DEMO_T1",
            "bars_sha256": "demo",
            "protocol_sha256": "demo",
            "initial_cash": "1000000",
        },
    }
    detail = dict(experiment)
    detail.update(
        {
            "nav_series": [
                {"date": "2025-01-02", "nav": "1000000"},
                {"date": "2025-01-03", "nav": "980000"},
                {"date": "2025-01-06", "nav": "920000"},
            ],
            "calendar_year_returns": {"2025": -0.08},
            "turnover_costs": None,
            "execution": {"fills": 4, "rejections": 1},
            "limitations": ["合成演示数据，不是研究结果"],
        }
    )
    body: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "demo",
        "overview": {
            "current_stage": "SYNTHETIC_DEMO",
            "registered_runs": 1,
            "valid_runs": 1,
            "not_evaluable_runs": 0,
            "retained_candidates": 0,
            "legacy_invalid_engineering_runs": 0,
            "economic_outcome": "DEMO_ONLY",
            "latest_prospective_date": None,
            "prospective_status": "DEMO_ONLY",
            "warnings": ["演示数据，不是研究结果"],
        },
        "studies": [{"study_id": "demo_study", "registered_runs": 1}],
        "experiments": [experiment],
        "experiment_details": {experiment["artifact_id"]: detail},
        "signals": {"historical": {}, "attribution": {}, "measurement": {}, "prospective": {}},
        "prospective": {
            "latest_date": None,
            "operations_status": "DEMO_ONLY",
            "input_status": "DEMO_ONLY",
            "data_capture_status": "DEMO_ONLY",
            "profitability_status": "DEMO_ONLY",
            "days": [],
            "accounts": {
                "engineering_warm_start": {"status": "NOT_STARTED", "latest": None},
                "fully_prospective_v1": {"status": "NOT_STARTED", "latest": None},
            },
            "warnings": ["演示数据，不是研究结果"],
        },
        "health": {
            "sources": [{"source_id": "demo", "verification_status": "SYNTHETIC"}],
            "system_observation": {"status": "DEMO_ONLY", "observed_at": None},
            "live_broker": "FORBIDDEN",
            "csi500": "NOT_READ",
        },
        "evidence": {
            experiment["evidence_id"]: {
                "source_kind": "synthetic_fixture",
                "sha256": "synthetic",
                "limitations": ["合成演示数据，不是研究结果"],
            }
        },
    }
    identifier = sha256(
        json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    body["snapshot_id"] = identifier
    destination = runtime / "snapshots" / identifier
    destination.mkdir(parents=True, exist_ok=True)
    snapshot_path = destination / "snapshot.json"
    snapshot_path.write_text(
        json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    (runtime / "current.json").write_text(json.dumps({"snapshot_id": identifier}), encoding="utf-8")
    return snapshot_path
