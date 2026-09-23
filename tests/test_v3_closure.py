"""Offline evidence, cache and causal-control checks for the closure revision."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import cast

import pandas as pd
import pytest
import yaml

from quant_stack.research_json import canonical_json
from quant_stack_v3.actions import load_no_participation_overrides
from quant_stack_v3.closure_dependencies import build as build_dependencies
from quant_stack_v3.closure_publication import publish, verify_inherited_evidence_archive
from quant_stack_v3.closure_rebuild import run as run_rebuild
from quant_stack_v3.closure_rebuild import verify_rebuild
from quant_stack_v3.closure_revision import build as build_revision_delta
from quant_stack_v3.protocol import Protocol
from quant_stack_v3.upgrade_parallel import run_upgrade_registry_parallel
from quant_stack_v3.upgrade_portfolio import policy_for, select_portfolio
from quant_stack_v3.upgrade_runner import (
    UpgradeInputs,
    UpgradeRunSpec,
    add_conditional_filter_liquidity_rank,
    load_cached_upgrade_result,
)
from quant_stack_v3.upgrade_statistics import _active_years


def test_closure_rights_evidence_verifies_archived_bytes_and_inheritance(tmp_path: Path) -> None:
    """A missing or changed issuer document cannot release a held-action gate."""
    base = tmp_path / "old.yaml"
    base.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "events": [
                    {
                        "symbol": "sh600001",
                        "effective_date": "2018-01-08",
                        "kind": "rights_issue",
                        "policy": "no_participation_no_synthetic_cash_or_shares",
                        "source_sha256": "a" * 64,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    raw = tmp_path / "evidence" / "raw"
    raw.mkdir(parents=True)
    source = b"%PDF-1.4\nissuer filing test bytes\n"
    digest = sha256(source).hexdigest()
    archived = raw / f"{digest}.pdf"
    archived.write_bytes(source)
    closure = tmp_path / "closure.yaml"
    closure.write_text(
        yaml.safe_dump(
            {
                "schema_version": 2,
                "inherits": {"path": "old.yaml", "sha256": sha256(base.read_bytes()).hexdigest()},
                "events": [
                    {
                        "symbol": "sz000001",
                        "effective_date": "2019-04-17",
                        "kind": "rights_issue",
                        "policy": "no_participation_no_synthetic_cash_or_shares",
                        "registration_date": "2019-04-08",
                        "listing_date": "2019-04-29",
                        "offered_ratio": "0.30",
                        "subscription_price": "4.65",
                        "record_shares": 1000,
                        "actual_issued_shares": 298,
                        "source_documents": [
                            {
                                "url": "https://issuer.example/plan.pdf",
                                "published_on": "2019-04-03",
                                "sha256": digest,
                                "pages": [1],
                            },
                            {
                                "url": "https://issuer.example/result.pdf",
                                "published_on": "2019-04-24",
                                "sha256": digest,
                                "pages": [2],
                            },
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert load_no_participation_overrides(closure, evidence_root=raw.parent) == {
        ("sh600001", date(2018, 1, 8)),
        ("sz000001", date(2019, 4, 17)),
    }
    archived.write_bytes(source + b"tamper")
    with pytest.raises(ValueError, match="source hash differs"):
        load_no_participation_overrides(closure, evidence_root=raw.parent)


def test_inherited_issuer_bytes_are_required_even_without_new_events(tmp_path: Path) -> None:
    """A schema-1 source URL/hash alone is not enough to release an action."""
    source = b"%PDF-1.4\nlegacy filing\n"
    digest = sha256(source).hexdigest()
    old = tmp_path / "old.yaml"
    old.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "events": [
                    {"symbol": "sh600001", "effective_date": "2018-01-08", "source_sha256": digest}
                ],
            }
        ),
        encoding="utf-8",
    )
    new = tmp_path / "new.yaml"
    new.write_text(
        yaml.safe_dump(
            {
                "schema_version": 2,
                "inherits": {"path": "old.yaml", "sha256": sha256(old.read_bytes()).hexdigest()},
                "events": [],
            }
        ),
        encoding="utf-8",
    )
    raw = tmp_path / "archive" / "raw"
    raw.mkdir(parents=True)
    with pytest.raises(ValueError, match="inherited issuer evidence bytes differ"):
        verify_inherited_evidence_archive(new, raw.parent)
    (raw / f"{digest}.pdf").write_bytes(source)
    assert verify_inherited_evidence_archive(new, raw.parent) == 1


def test_cache_reuse_rejects_input_and_child_artifact_drift(tmp_path: Path) -> None:
    """A matching directory name alone does not authorize cached economics."""
    result_path = tmp_path / "result.json"
    expected = {"bars_sha256": "a" * 64, "experiment": {"strategy_id": "B50"}}
    payload = {
        "run_identity": "b" * 64,
        "RESEARCH_VALIDITY": "VALID_RETROSPECTIVE",
        "identities": expected | {"nav_sha256": "c" * 64},
    }
    result_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match=r"nav\.parquet hash differs"):
        load_cached_upgrade_result(result_path, "b" * 64, expected)
    with pytest.raises(ValueError, match="input identities differ"):
        load_cached_upgrade_result(result_path, "b" * 64, expected | {"new_fact": True})


def test_closure_matrix_refuses_result_cache_even_with_matching_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A prior JSON cannot be republished as a fresh closure evaluation."""
    identity = sha256(canonical_json({"fixed": True})).hexdigest()
    existing = tmp_path / "runs" / identity
    existing.mkdir(parents=True)
    (existing / "result.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr("quant_stack_v3.upgrade_parallel.prepare_upgrade_data", lambda *_: None)
    monkeypatch.setattr("quant_stack_v3.upgrade_parallel._identities", lambda *_: {"fixed": True})
    inputs = UpgradeInputs(
        bundle_root=tmp_path,
        bundle_sha256="a" * 64,
        bars_path=tmp_path / "bars.h5",
        scores_path=tmp_path / "scores.parquet",
        artifact_root=tmp_path,
        base_protocol_path=tmp_path / "base.yaml",
        protocol_path=tmp_path / "upgrade.yaml",
        action_overrides_path=tmp_path / "actions.yaml",
        closure_protocol_path=tmp_path / "closure.yaml",
    )
    spec = UpgradeRunSpec("test", "B50_LIQ50_D20", "REAL_T1_1M", Decimal(1), 1, "real")
    with pytest.raises(ValueError, match="cache reuse is disallowed"):
        run_upgrade_registry_parallel(cast(Protocol, None), (spec,), inputs, maximum_workers=1)


def test_conditional_control_uses_only_gated_trailing_amount() -> None:
    """The diagnostic cannot select an excluded high-liquidity name."""
    daily = pd.DataFrame(
        {
            "symbol": [f"sh{index:06d}" for index in range(51)],
            "COND_REV_5_rank": [float(index + 1) for index in range(50)] + [float("nan")],
            "mean_amount_60": [float(index + 1) for index in range(51)],
            "liquidity_rank": [index + 1 for index in range(51)],
        }
    )
    ranked = add_conditional_filter_liquidity_rank(daily)
    selected = select_portfolio(ranked, frozenset(), policy_for("COND_FILTER_LIQ50_D20_EQ"))
    assert len(selected.symbols) == 50
    assert selected.symbols[0] == "sh000049"
    assert "sh000050" not in selected.symbols
    assert "COND_FILTER_LIQ_rank" not in daily


def test_public_evidence_index_links_failure_without_local_source_paths(tmp_path: Path) -> None:
    """Publication links an unresolved run to issuer hashes, not to raw files."""
    evidence_root = tmp_path / "evidence"
    raw = evidence_root / "raw"
    raw.mkdir(parents=True)
    source = b"%PDF-1.4\nsynthetic filing\n"
    digest = sha256(source).hexdigest()
    (raw / f"{digest}.pdf").write_bytes(source)
    base = tmp_path / "base.yaml"
    base.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "events": [
                    {
                        "symbol": "sh600001",
                        "effective_date": "2018-01-08",
                        "kind": "rights_issue",
                        "policy": "no_participation_no_synthetic_cash_or_shares",
                        "source_url": "https://issuer.example/legacy.pdf",
                        "source_sha256": digest,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    action = tmp_path / "actions.yaml"
    document = {
        "url": "https://issuer.example/filing.pdf",
        "published_on": "2019-04-17",
        "retrieved_at_utc": "2026-09-23T06:55:17Z",
        "sha256": digest,
        "pages": [1],
    }
    action.write_text(
        yaml.safe_dump(
            {
                "schema_version": 2,
                "inherits": {"path": "base.yaml", "sha256": sha256(base.read_bytes()).hexdigest()},
                "events": [
                    {
                        "symbol": "sz000001",
                        "effective_date": "2019-04-17",
                        "kind": "rights_issue",
                        "policy": "no_participation_no_synthetic_cash_or_shares",
                        "registration_date": "2019-04-08",
                        "listing_date": "2019-04-29",
                        "offered_ratio": "0.30",
                        "subscription_price": "4.65",
                        "record_shares": 1000,
                        "actual_issued_shares": 298,
                        "source_documents": [document, document],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    artifact_root = tmp_path / "artifacts"
    run_id = "b" * 64
    run_root = artifact_root / "runs" / run_id
    run_root.mkdir(parents=True)
    (run_root / "result.json").write_text(
        json.dumps({"failure": "held position has unexplained action on 2019-04-17: sz000001"}),
        encoding="utf-8",
    )
    matrix = tmp_path / "matrix.json"
    matrix.write_text(
        json.dumps(
            {
                "result_identities": {"test": run_id},
                "candidate_outcomes": {"test": "NOT_EVALUABLE"},
            }
        ),
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "matrix_sha256": sha256(matrix.read_bytes()).hexdigest(),
                "DATA_USE_LEVEL": "PRIVATE_RESEARCH_ONLY",
                "retained_candidates": 0,
            }
        ),
        encoding="utf-8",
    )
    publish(matrix, manifest, action, evidence_root, artifact_root, None)
    index_path = next((artifact_root / "evidence").glob("*.json"))
    index = json.loads(index_path.read_text(encoding="utf-8"))
    assert len(index["run_evidence"][run_id]) == 1
    assert any("legacy.pdf" in str(record["source_url"]) for record in index["records"].values())
    assert "issuer.example" in json.dumps(index["records"])
    assert str(tmp_path) not in json.dumps(index)
    published = json.loads(next((artifact_root / "manifests").glob("*.json")).read_text())
    assert published["ECONOMIC_OUTCOME"] == "MIXED_EVALUABILITY_NO_RETAINED_CANDIDATE"
    assert published["source_commit"] == "UNCOMMITTED_UNVALIDATED"
    assert (
        published["result_sha256s"][run_id]
        == sha256((run_root / "result.json").read_bytes()).hexdigest()
    )
    with pytest.raises(ValueError, match="matching clean worktree"):
        publish(matrix, manifest, action, evidence_root, artifact_root, "a" * 40)
    (raw / f"{digest}.pdf").write_bytes(source + b"tampered")
    with pytest.raises(ValueError, match=r"source hash differs|evidence bytes differ"):
        publish(matrix, manifest, action, evidence_root, artifact_root, None)


def test_shared_benchmark_failure_maps_to_all_registered_comparisons(tmp_path: Path) -> None:
    """A failed B50 run blocks its seven formal candidate comparisons."""
    artifacts = tmp_path / "old-artifacts"
    benchmark_id, candidate_id = "1" * 64, "2" * 64
    for identity, strategy, validity, failure in (
        (
            benchmark_id,
            "B50_LIQ50_D20",
            "NOT_EVALUABLE",
            "held position has unexplained action on 2019-04-17: sh601012",
        ),
        (candidate_id, "AF7_TOP50_D20_EQ", "VALID_RETROSPECTIVE", ""),
    ):
        run_root = artifacts / "runs" / identity
        run_root.mkdir(parents=True)
        (run_root / "result.json").write_text(
            json.dumps(
                {"strategy_id": strategy, "RESEARCH_VALIDITY": validity, "failure": failure}
            ),
            encoding="utf-8",
        )
    matrix = tmp_path / "old-matrix.json"
    matrix.write_text(
        json.dumps(
            {
                "result_identities": {
                    "B50_LIQ50_D20__REAL_T1_1M": benchmark_id,
                    "AF7_TOP50_D20_EQ__REAL_T1_1M": candidate_id,
                }
            }
        ),
        encoding="utf-8",
    )
    build_dependencies(matrix, artifacts, tmp_path / "output")
    graph = json.loads(next((tmp_path / "output" / "dependency").glob("*.json")).read_text())
    assert graph["valid_runs"] == 1
    assert graph["events"][0]["symbol"] == "sh601012"
    assert graph["events"][0]["comparison_count"] == 7


def test_no_cache_rebuild_requires_identical_account_artifacts(tmp_path: Path) -> None:
    """A matching result JSON cannot hide a changed persisted ledger or NAV."""
    paths = []
    for name in ("source", "rebuilt"):
        run_root = tmp_path / name
        run_root.mkdir()
        (run_root / "result.json").write_text(
            json.dumps({"run_identity": "a" * 64}), encoding="utf-8"
        )
        (run_root / "nav.parquet").write_bytes(b"same source bytes")
        paths.append(run_root / "result.json")
    report = verify_rebuild(paths[0], paths[1])
    assert report["status"] == "INDEPENDENT_NO_CACHE_REBUILD_PASS"
    (paths[1].parent / "nav.parquet").write_bytes(b"changed")
    with pytest.raises(ValueError, match=r"nav\.parquet content differs"):
        verify_rebuild(paths[0], paths[1])


def test_no_cache_rebuild_rejects_prepopulated_target(tmp_path: Path) -> None:
    """A copied run cannot masquerade as an independently recomputed run."""
    target = tmp_path / "target"
    target.mkdir()
    (target / "copied-result.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="new empty artifact root"):
        run_rebuild(
            experiment_id="B50_LIQ50_D20__REAL_T1_1M",
            source_matrix=tmp_path / "missing-matrix.json",
            source_artifacts=tmp_path / "source",
            rebuild_artifacts=target,
            bundle_root=tmp_path / "bundle",
            bars_path=tmp_path / "bars.h5",
            scores_path=tmp_path / "scores.parquet",
            evidence_root=tmp_path / "evidence",
            action_evidence=tmp_path / "actions.yaml",
            closure_protocol=tmp_path / "protocol.yaml",
        )


def test_paired_years_cannot_silently_drop_an_unfavorable_year() -> None:
    """A missing benchmark year invalidates the pair, not the adverse sample."""
    candidate = {"calendar_year_returns": {"2017": -0.2, "2018": 0.1}}
    benchmark = {"calendar_year_returns": {"2018": 0.0}}
    with pytest.raises(ValueError, match="yearly periods differ"):
        _active_years(candidate, benchmark)


def test_revision_delta_keeps_invalid_old_metrics_uncomputed(tmp_path: Path) -> None:
    """Restoring a blocked run does not invent an old return for the delta."""
    old_root, new_root = tmp_path / "old", tmp_path / "new"
    old_id, new_id = "a" * 64, "b" * 64
    for root, identity, validity, metrics in (
        (old_root, old_id, "NOT_EVALUABLE", None),
        (new_root, new_id, "VALID_RETROSPECTIVE", {"cagr": -0.05}),
    ):
        destination = root / "runs" / identity
        destination.mkdir(parents=True)
        (destination / "result.json").write_text(
            json.dumps({"RESEARCH_VALIDITY": validity, "metrics": metrics, "failure": "blocked"}),
            encoding="utf-8",
        )
    old_matrix = tmp_path / "old-matrix.json"
    new_matrix = tmp_path / "new-matrix.json"
    old_matrix.write_text(json.dumps({"result_identities": {"BENCH": old_id}}), encoding="utf-8")
    new_matrix.write_text(
        json.dumps(
            {
                "result_identities": {"BENCH": new_id},
                "lineage": {"BENCH": {"revision_of": old_id, "new_run_identity": new_id}},
            }
        ),
        encoding="utf-8",
    )
    build_revision_delta(old_matrix, old_root, new_matrix, new_root, tmp_path / "out")
    report = json.loads(next((tmp_path / "out" / "revision_delta").glob("*.json")).read_text())
    assert report["transition_counts"] == {"NOT_EVALUABLE_TO_VALID": 1}
    assert report["runs"]["BENCH"]["metric_deltas"] is None
