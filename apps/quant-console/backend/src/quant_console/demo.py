"""Explicit synthetic snapshot for CI and visibly labelled demonstration mode."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from quant_console.snapshot import SNAPSHOT_SCHEMA_VERSION, publish_read_model

DEMO_DIGEST = "d" * 64


def _metric(name: str, value: float, unit: str, evidence_id: str) -> dict[str, Any]:
    return {
        "name": name,
        "value": value,
        "unit": unit,
        "validity": "VALID",
        "unavailable_reason": None,
        "basis": "synthetic_demo_full_period",
        "scenario_id": "DEMO_T1",
        "data_use_level": "SYNTHETIC",
        "source_evidence_id": evidence_id,
    }


def publish_demo(runtime: Path) -> Path:
    """Publish a small synthetic read model that can never look like real research."""
    artifact_id = "demo:synthetic-run-001"
    evidence_id = "evidence:demo:synthetic-run-001"
    metrics = {
        "cagr": _metric("cagr", -0.03, "ratio", evidence_id),
        "total_return": _metric("total_return", -0.08, "ratio", evidence_id),
        "annualized_volatility": _metric("annualized_volatility", 0.18, "ratio", evidence_id),
        "maximum_drawdown": _metric("maximum_drawdown", -0.15, "ratio", evidence_id),
        "sharpe_ratio": _metric("sharpe_ratio", -0.1, "ratio", evidence_id),
        "turnover": _metric("turnover", 3.0, "two_sided_ratio", evidence_id),
        "total_transaction_costs": _metric("total_transaction_costs", 1234.5, "CNY", evidence_id),
    }
    experiment: dict[str, Any] = {
        "artifact_id": artifact_id,
        "evidence_id": evidence_id,
        "study_id": "demo_study",
        "study_revision": DEMO_DIGEST,
        "experiment_id": "SYNTHETIC_A",
        "run_identity": DEMO_DIGEST,
        "strategy_id": "SYNTHETIC_A",
        "family": "DEMO",
        "scenario_id": "DEMO_T1",
        "data_evaluability": "VALID",
        "benchmark_comparability": "COMPARABLE",
        "economic_outcome": "DEMO_ONLY",
        "engineering_status": "DEMO_ONLY",
        "research_validity": "SYNTHETIC_NOT_RESEARCH",
        "data_use_level": "SYNTHETIC",
        "metrics": metrics,
        "failure_reason": None,
        "period": {"start": "2025-01-02", "end": "2025-01-06", "sessions": 3},
        "matched_benchmark_id": None,
        "revision_of": None,
    }
    detail = {
        **experiment,
        "nav_series": [
            {"date": "2025-01-02", "nav": "1000000"},
            {"date": "2025-01-03", "nav": "980000"},
            {"date": "2025-01-06", "nav": "920000"},
        ],
        "calendar_year_returns": {"2025": -0.08},
        "turnover_costs": None,
        "execution": {"fills": 4, "rejections": 1},
        "identities": {"nav_sha256": DEMO_DIGEST},
        "limitations": ["合成演示数据，不是研究结果"],
        "compatibility": {
            "study_revision": DEMO_DIGEST,
            "scenario_id": "DEMO_T1",
            "bars_sha256": DEMO_DIGEST,
            "protocol_sha256": DEMO_DIGEST,
            "base_protocol_sha256": DEMO_DIGEST,
            "portfolio_sha256": DEMO_DIGEST,
            "scores_sha256": DEMO_DIGEST,
            "signals_sha256": DEMO_DIGEST,
            "initial_cash": "1000000",
            "cost_mode": "synthetic",
            "execution_delay_sessions": 1,
        },
        "source_sha256": DEMO_DIGEST,
        "series": [],
        "curve_unavailable_reason": None,
    }
    body: dict[str, Any] = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
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
        "studies": [
            {
                "study_id": "demo_study",
                "study_revision": DEMO_DIGEST,
                "schema_version": 1,
                "code_commit": None,
                "implementation_status": "DEMO_ONLY",
                "research_validity": "SYNTHETIC_NOT_RESEARCH",
                "economic_outcome": "DEMO_ONLY",
                "data_use_level": "SYNTHETIC",
                "registered_runs": 1,
            }
        ],
        "experiments": [experiment],
        "experiment_details": {artifact_id: detail},
        "signals": {
            "historical": {},
            "attribution": {},
            "measurement": {},
            "prospective": {},
        },
        "prospective": {
            "latest_date": None,
            "operations_status": "DEMO_ONLY",
            "input_status": "DEMO_ONLY",
            "data_capture_status": "DEMO_ONLY",
            "profitability_status": "DEMO_ONLY",
            "days": [],
            "accounts": {
                "engineering_warm_start": {
                    "status": "NOT_STARTED",
                    "latest": None,
                    "observed_days": 0,
                },
                "fully_prospective_v1": {
                    "status": "NOT_STARTED",
                    "latest": None,
                    "observed_days": 0,
                },
            },
            "diagnostics": {},
            "warnings": ["演示数据，不是研究结果"],
            "evidence_id": evidence_id,
        },
        "health": {
            "sources": [
                {
                    "source_id": "demo",
                    "verification_status": "SYNTHETIC",
                    "manifest_sha256": None,
                    "matrix_sha256": None,
                }
            ],
            "system_observation": {
                "status": "DEMO_ONLY",
                "observed_at": None,
                "timer": None,
                "service": None,
                "unit_hashes": None,
            },
            "live_broker": "FORBIDDEN",
            "csi500": "NOT_READ",
        },
        "evidence": {
            evidence_id: {
                "source_kind": "synthetic_fixture",
                "study_id": "demo_study",
                "run_identity": DEMO_DIGEST,
                "sha256": DEMO_DIGEST,
                "schema_version": 1,
                "data_use_level": "SYNTHETIC",
                "limitations": ["合成演示数据，不是研究结果"],
                "absolute_paths_exposed": False,
            }
        },
    }
    return publish_read_model(body, runtime)
