"""Offline contract tests for the isolated Quant V2 external-data registry."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest
import typer
import yaml
from pydantic import ValidationError
from typer.testing import CliRunner

import quant_stack.cli as cli
import quant_stack_v2.dataset_registry as registry_module
from quant_stack_v2.dataset_registry import (
    DatasetRegistry,
    DatasetRegistryError,
    DatasetValidation,
    capture_dataset,
    list_dataset_registries,
    load_dataset_registry,
    validate_dataset,
)

ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


def _payload(content: bytes = b"fixture") -> dict[str, object]:
    digest = sha256(content).hexdigest()
    return {
        "schema_version": 1,
        "dataset_id": "test_dataset",
        "source_repository": "owner/repository",
        "source_commit": "a" * 40,
        "source_release": "v1.0.0",
        "source_release_kind": "github_release",
        "retrieved_at_utc": None,
        "usage_level": "RESEARCH_ADJUSTED_ONLY",
        "qualification_status": "PENDING_CAPTURE_AND_INSPECTION",
        "license": {
            "code_license": "MIT",
            "market_data_rights_reviewed": False,
            "redistribution_permitted": False,
            "notes": "fixture only",
        },
        "artifacts": {
            "archive_url": None,
            "archive_sha256": None,
            "manifest_url": "https://github.com/owner/repository/releases/download/v1.0.0/manifest.json",
            "manifest_sha256": digest,
            "manifest_bindings": {"release": "v1.0.0", "commit": "a" * 40},
        },
        "coverage": {
            "market": "TEST",
            "frequency": "1d",
            "first_date": "2020-01-01",
            "last_date": "2020-12-31",
        },
        "semantics": {
            "price_type": "adjusted",
            "raw_price_recoverable": False,
            "adjustment_definition": "test adjusted close",
            "historical_membership": True,
            "corporate_actions_officially_verified": False,
        },
        "allowed_uses": ["engineering", "exploratory_research"],
        "forbidden_uses": ["execution", "live_order", "fresh_holdout_claim", "redistribution"],
    }


def _write(path: Path, payload: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def test_checked_in_registries_load_without_network() -> None:
    records = list_dataset_registries(ROOT / "configs/v2/datasets")
    assert [record.dataset_id for record in records] == sorted(
        record.dataset_id for record in records
    )
    assert len(records) == 5
    assert all("live_order" in record.forbidden_uses for record in records)


def test_v2_cli_roots_cannot_be_nested_inside_v1_authorities(tmp_path: Path) -> None:
    assert cli._v2_external_root(ROOT / "data" / "external") == (ROOT / "data" / "external")
    with pytest.raises(typer.BadParameter, match="repository or sealed"):
        cli._v2_external_root(tmp_path / "data" / "raw" / "data" / "external")
    with pytest.raises(typer.BadParameter, match="repository or sealed"):
        cli._v2_artifact_root(tmp_path / "artifacts" / "data_qualification" / "v2")


@pytest.mark.parametrize("field", ["source_commit", "source_release"])
def test_registry_rejects_missing_source_pin(field: str) -> None:
    payload = _payload()
    payload.pop(field)
    with pytest.raises(ValidationError):
        DatasetRegistry.model_validate(payload)


def test_formal_research_without_archive_hash_fails_closed(tmp_path: Path) -> None:
    payload = _payload()
    payload["artifacts"] = {
        "archive_url": "https://github.com/owner/repository/releases/download/v1.0.0/data.tar.gz",
        "archive_sha256": None,
        "manifest_url": None,
        "manifest_sha256": None,
    }
    path = _write(tmp_path / "registry.yaml", payload)
    result = validate_dataset(path, tmp_path / "data/external")
    assert not result.qualified
    assert "archive_sha256_missing" in result.reasons


def test_registry_rejects_undeclared_adjustment_semantics() -> None:
    payload = _payload()
    payload["semantics"]["adjustment_definition"] = ""  # type: ignore[index]
    with pytest.raises(ValidationError, match="adjustment semantics"):
        DatasetRegistry.model_validate(payload)


def test_adjusted_research_data_cannot_enter_execution() -> None:
    registry = DatasetRegistry.model_validate(_payload())
    with pytest.raises(DatasetRegistryError, match="not allowed"):
        registry.require_use("execution")


def test_pending_backtest_registry_cannot_authorize_external_test(tmp_path: Path) -> None:
    registry = load_dataset_registry(ROOT / "configs/v2/datasets/qlib_cn_community_v1.yaml")
    validation = validate_dataset(
        ROOT / "configs/v2/datasets/qlib_cn_community_v1.yaml", tmp_path / "data/external"
    )
    with pytest.raises(DatasetRegistryError, match="qualified local validation"):
        registry.require_use("external_retrospective_test", validation)


def test_unreviewed_rights_must_forbid_redistribution() -> None:
    payload = _payload()
    payload["forbidden_uses"] = ["execution", "live_order", "fresh_holdout_claim"]
    with pytest.raises(ValidationError, match="forbid redistribution"):
        DatasetRegistry.model_validate(payload)


def test_unreviewed_rights_cannot_claim_redistribution_permission() -> None:
    payload = _payload()
    payload["license"]["redistribution_permitted"] = True  # type: ignore[index]
    with pytest.raises(ValidationError, match="cannot permit redistribution"):
        DatasetRegistry.model_validate(payload)


def test_backtest_level_requires_historical_membership() -> None:
    payload = _payload()
    payload["usage_level"] = "BACKTEST_RESEARCH"
    payload["semantics"]["historical_membership"] = False  # type: ignore[index]
    with pytest.raises(ValidationError, match="historical membership"):
        DatasetRegistry.model_validate(payload)


def test_artifact_url_must_match_repository_and_release() -> None:
    payload = _payload()
    payload["artifacts"]["manifest_url"] = (  # type: ignore[index]
        "https://github.com/other/repository/releases/download/v1.0.0/manifest.json"
    )
    with pytest.raises(ValidationError, match="repository or release pin"):
        DatasetRegistry.model_validate(payload)


def test_release_url_cannot_embed_expected_path_under_another_repository() -> None:
    payload = _payload()
    payload["artifacts"]["manifest_url"] = (  # type: ignore[index]
        "https://github.com/attacker/repository/blob/main/owner/repository/"
        "releases/download/v1.0.0/manifest.json"
    )
    with pytest.raises(ValidationError, match="repository or release pin"):
        DatasetRegistry.model_validate(payload)


def test_artifact_url_must_use_https() -> None:
    payload = _payload()
    payload["artifacts"]["manifest_url"] = (  # type: ignore[index]
        "http://github.com/owner/repository/releases/download/v1.0.0/manifest.json"
    )
    with pytest.raises(ValidationError, match=r"github\.com HTTPS"):
        DatasetRegistry.model_validate(payload)


def test_unknown_release_kind_cannot_disable_url_binding() -> None:
    payload = _payload()
    payload["source_repository"] = "other/repository"
    payload["source_release"] = "unrelated"
    payload["source_release_kind"] = "unknown"
    with pytest.raises(ValidationError):
        DatasetRegistry.model_validate(payload)


def test_manifest_bindings_must_match_top_level_pins() -> None:
    payload = _payload()
    payload["artifacts"]["manifest_bindings"] = {  # type: ignore[index]
        "release": "v1.0.0",
        "commit": "b" * 40,
    }
    with pytest.raises(ValidationError, match="release and commit pins"):
        DatasetRegistry.model_validate(payload)


def test_commit_snapshot_binds_release_and_artifact_url() -> None:
    payload = _payload()
    payload["source_release_kind"] = "commit_snapshot"
    payload["source_release"] = f"commit-{'a' * 40}"
    payload["artifacts"] = {
        "archive_url": (f"https://github.com/owner/repository/archive/{'a' * 40}.tar.gz"),
        "archive_sha256": "b" * 64,
        "manifest_url": None,
        "manifest_sha256": None,
        "manifest_bindings": {},
    }
    DatasetRegistry.model_validate(payload)
    payload["source_release"] = f"commit-{'c' * 40}"
    with pytest.raises(ValidationError, match="bind the source commit"):
        DatasetRegistry.model_validate(payload)


def test_commit_snapshot_rejects_commit_prefix_collision() -> None:
    payload = _payload()
    payload["source_release_kind"] = "commit_snapshot"
    payload["source_release"] = f"commit-{'a' * 40}"
    payload["artifacts"] = {
        "archive_url": (f"https://github.com/owner/repository/archive/{'a' * 40}extra.tar.gz"),
        "archive_sha256": "b" * 64,
        "manifest_url": None,
        "manifest_sha256": None,
        "manifest_bindings": {},
    }
    with pytest.raises(ValidationError, match="repository or commit pin"):
        DatasetRegistry.model_validate(payload)


@pytest.mark.parametrize(
    ("status", "dataset_id", "registry_sha256"),
    [
        ("PENDING_CAPTURE_AND_INSPECTION", "test_dataset", "current"),
        ("QUALIFIED", "other_dataset", "current"),
        ("QUALIFIED", "test_dataset", "0" * 64),
    ],
)
def test_formal_use_rejects_pending_foreign_or_stale_validation(
    status: str, dataset_id: str, registry_sha256: str
) -> None:
    payload = _payload()
    payload["usage_level"] = "BACKTEST_RESEARCH"
    payload["qualification_status"] = status
    payload["allowed_uses"] = ["external_retrospective_test"]
    registry = DatasetRegistry.model_validate(payload)
    validation = DatasetValidation(
        dataset_id=dataset_id,
        registry_sha256=(
            registry.identity_sha256 if registry_sha256 == "current" else registry_sha256
        ),
        qualified=True,
        reasons=(),
        archive_path="archive",
        manifest_path="manifest",
    )
    with pytest.raises(DatasetRegistryError, match="qualified local validation"):
        registry.require_use("external_retrospective_test", validation)


def test_capture_is_content_addressed_idempotent_and_deterministic(tmp_path: Path) -> None:
    content = f'{{"release":"v1.0.0","commit":"{"a" * 40}","manifest":1}}'.encode()
    path = _write(tmp_path / "registry.yaml", _payload(content))
    captured_at = datetime(2026, 9, 11, tzinfo=UTC)
    first = capture_dataset(
        path,
        tmp_path / "a/data/external",
        allow_network=True,
        fetcher=lambda _: content,
        captured_at=captured_at,
    )
    second = capture_dataset(
        path,
        tmp_path / "a/data/external",
        allow_network=True,
        fetcher=lambda _: content,
        captured_at=captured_at,
    )
    rebuilt = capture_dataset(
        path,
        tmp_path / "b/data/external",
        allow_network=True,
        fetcher=lambda _: content,
        captured_at=captured_at,
    )
    assert first == second
    assert first[-1].read_bytes() == rebuilt[-1].read_bytes()
    assert first[0].parent.name == sha256(content).hexdigest()


def test_changed_source_never_overwrites_old_snapshot(tmp_path: Path) -> None:
    old = f'{{"release":"v1.0.0","commit":"{"a" * 40}","value":"old"}}'.encode()
    new = f'{{"release":"v1.0.0","commit":"{"b" * 40}","value":"new"}}'.encode()
    path = _write(tmp_path / "registry.yaml", _payload(old))
    first = capture_dataset(
        path, tmp_path / "data/external", allow_network=True, fetcher=lambda _: old
    )
    updated = _payload(new)
    updated["source_commit"] = "b" * 40
    updated["artifacts"]["manifest_bindings"]["commit"] = "b" * 40  # type: ignore[index]
    _write(path, updated)
    second = capture_dataset(
        path, tmp_path / "data/external", allow_network=True, fetcher=lambda _: new
    )
    assert first[0] != second[0]
    assert first[0].read_bytes() == old
    assert second[0].read_bytes() == new


def test_capture_requires_network_flag_and_preserves_v1_authority(tmp_path: Path) -> None:
    path = _write(tmp_path / "registry.yaml", _payload())
    v1 = tmp_path / "artifacts/issue009/locked_runs/sentinel/attempt.json"
    v1.parent.mkdir(parents=True)
    v1.write_bytes(b"immutable-v1")
    with pytest.raises(DatasetRegistryError, match="allow-network"):
        capture_dataset(path, tmp_path / "data/external", allow_network=False)
    assert v1.read_bytes() == b"immutable-v1"


def test_successful_capture_cannot_escape_v2_data_root(tmp_path: Path) -> None:
    payload = _payload(b"fixture")
    payload["dataset_id"] = "../../artifacts/issue009/injected"
    with pytest.raises(ValidationError):
        DatasetRegistry.model_validate(payload)
    path = _write(tmp_path / "registry.yaml", _payload())
    with pytest.raises(DatasetRegistryError, match="data/external"):
        capture_dataset(
            path,
            tmp_path / "artifacts/issue009",
            allow_network=True,
            fetcher=lambda _: b"fixture",
        )


def test_manifest_must_bind_declared_repository_release_and_commit(tmp_path: Path) -> None:
    content = b'{"release_tag":"wrong","investment_data_commit":"wrong"}'
    payload = _payload(content)
    payload["artifacts"]["manifest_bindings"] = {  # type: ignore[index]
        "release_tag": "v1.0.0",
        "investment_data_commit": "a" * 40,
    }
    path = _write(tmp_path / "registry.yaml", payload)
    with pytest.raises(DatasetRegistryError, match="manifest content"):
        capture_dataset(
            path,
            tmp_path / "data/external",
            allow_network=True,
            fetcher=lambda _: content,
        )


def test_production_capture_streams_bounded_chunks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = b"x" * (1024 * 1024 + 17)

    class Response:
        def __init__(self) -> None:
            self.offset = 0

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, size: int) -> bytes:
            assert size == 1024 * 1024
            chunk = content[self.offset : self.offset + size]
            self.offset += len(chunk)
            return chunk

    monkeypatch.setattr(registry_module, "urlopen", lambda *_args, **_kwargs: Response())
    destination = tmp_path / "data/external/test" / sha256(content).hexdigest() / "archive.bin"
    registry_module._fetch_to_immutable(
        "https://github.com/owner/repository/releases/download/v1/archive.bin",
        destination,
        sha256(content).hexdigest(),
    )
    assert destination.read_bytes() == content


def test_v2_cli_lists_inspects_and_fails_closed_on_uncaptured_data() -> None:
    listed = runner.invoke(cli.app, ["v2", "dataset", "list"])
    inspected = runner.invoke(cli.app, ["v2", "dataset", "inspect", "qlib_cn_community_v1"])
    validated = runner.invoke(cli.app, ["v2", "dataset", "validate", "qlib_cn_community_v1"])
    assert listed.exit_code == 0 and "qlib_cn_community_v1" in listed.output
    assert inspected.exit_code == 0 and "PENDING_CAPTURE_AND_INSPECTION" in inspected.output
    assert validated.exit_code == 1 and "coverage_unverified" in validated.output
