"""Issue 009 V2 precommit creation and single-use locked-test execution."""

from __future__ import annotations

import json
import os
import platform
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import cast

import numpy as np
import pandas as pd
import pyarrow  # type: ignore[import-untyped]

from quant_stack.d0_inventory import load_d0_source_registry
from quant_stack.data.models import CanonicalDatasetManifest
from quant_stack.models import PriceBasis
from quant_stack.research_json import canonical_json
from quant_stack.snapshot import write_immutable
from quant_stack.walk_forward import (
    load_preregistered_experiment,
    verify_declared_config_hashes,
)

PRECOMMIT_VERSION = "1.0.0"
RECOVERY_PRECOMMIT_VERSION = "2.0.0"
RECOVERY_MODE = "controlled_recovery_after_persistence_failure"
V2_PRECOMMIT_ID = "d1c3c371864885134f4a733cebdc09b0fedcd2ca69ad7a8a9c1898c4374fe7c6"
V2_PRECOMMIT_FILE_SHA256 = "0af4dc26b5f72e947830fa6aac3b1dbc3d826a6bc2eeeae5874dfe77329c34c1"
V2_ATTEMPT_SHA256 = "ee0a73f596b7dfc79892c919526f1fa5845c3e40325726d6804c35dc4af1195e"
V2_FAILURE_SHA256 = "f363c065c07ed96e44b5136326c9b6773d6e5114d2ca5c4092af1ba3734a7820"
V2_DATA_SNAPSHOT_ID = "6f33e58c7681a3444d05933d7605672a22940ca5a5039b748d962c419fea4750"
V2_QUALIFICATION_ID = "66ed03b7fda4057fac1a1f5ab916443d66fe87fe30ab5a6903e67433cc20978a"
V3_EXPERIMENT_SHA256 = "55e9c3610cd1c8d7988a1c513ad0224070841a59c588d4690969b714845282fb"
V3_EXPERIMENT_PATH = "configs/experiments/etf_walk_forward_v3.yaml"
V3_AUTHORIZATION_PATH = "configs/experiments/CONTROLLED_RECOVERY_AUTHORIZATION_V3.json"
V2_WALK_FORWARD_SPLIT_SHA256 = "83630da354cc4de65c99441f671875966ddbf406c68694056cd4c160e6742b7d"


@dataclass(frozen=True)
class LockedAssetInput:
    """Exact raw and causal identities frozen for one locked-test asset."""

    symbol: str
    exchange: str
    raw_manifest_id: str
    raw_normalized_sha256: str
    causal_manifest_id: str
    causal_output_sha256: str
    ledger_sha256: str
    reproduction_report_id: str


@dataclass(frozen=True)
class LockedTestPrecommit:
    """Content-addressed Issue 009 execution authorization frozen before results."""

    precommit_id: str
    version: str
    status: str
    experiment_id: str
    code_commit: str
    tracked_tree_sha256: str
    data_snapshot_id: str
    qualification_report_id: str
    qualification_report_sha256: str
    source_registry_sha256: str
    source_registry_path: str
    experiment_config_path: str
    experiment_config_sha256: str
    config_hashes: dict[str, str]
    walk_forward_split_sha256: str
    selection_period_end: str
    locked_test_start: str
    locked_test_end: str
    last_locked_signal_date: str
    random_seed: int
    assets: tuple[LockedAssetInput, ...]
    protocol_mode: str = "fresh_holdout"
    predecessor_precommit_id: str | None = None
    predecessor_attempt_sha256: str | None = None
    predecessor_failure_sha256: str | None = None
    predecessor_precommit_file_sha256: str | None = None
    run_plan_names: tuple[str, ...] = ()
    holdout_status: str = "FRESH"
    authorized_builds: tuple[str, ...] = ("build_a",)
    retry_count: int = 0

    def as_dict(self) -> dict[str, object]:
        """Return the stable JSON representation including its content identity."""
        payload = asdict(self)
        payload["assets"] = [asdict(asset) for asset in self.assets]
        return payload


def create_locked_test_precommit(
    repository_root: Path,
    data_root: Path,
    experiment_path: Path,
    qualification_path: Path,
    source_registry_path: Path,
    output_path: Path,
) -> LockedTestPrecommit:
    """Freeze executable code, D0-qualified data, configs, periods, and split identity."""
    _require_clean_tracked_tree(repository_root)
    experiment = load_preregistered_experiment(experiment_path)
    recovery = _controlled_recovery(experiment)
    if recovery is None:
        reject_consumed_holdout(
            _date_string(experiment, "locked_test_start"),
            _date_string(experiment, "locked_test_end"),
        )
    else:
        if (
            experiment_path.relative_to(repository_root).as_posix() != V3_EXPERIMENT_PATH
            or sha256(experiment_path.read_bytes()).hexdigest() != V3_EXPERIMENT_SHA256
            or output_path.relative_to(repository_root).as_posix() != V3_AUTHORIZATION_PATH
        ):
            raise ValueError("controlled recovery must use the exact authorized V3 files")
        _verify_v2_failure_archive(repository_root)
        _verify_recovery_runtime(experiment)
    verify_declared_config_hashes(experiment, repository_root)
    config_hashes = _string_mapping(experiment.get("frozen_config_sha256"), "config hashes")
    registry_relative = _string(experiment, "source_registry_path")
    frozen_registry_path = (repository_root / registry_relative).resolve()
    if source_registry_path.resolve() != frozen_registry_path:
        raise ValueError("source registry path differs from the frozen experiment")
    qualification_bytes = qualification_path.read_bytes()
    qualification = json.loads(qualification_bytes)
    if not isinstance(qualification, dict) or qualification.get("all_qualified") is not True:
        raise ValueError("locked test requires an all-qualified D0 report")
    qualification_id = qualification_path.parent.name
    if recovery is not None and qualification_id != V2_QUALIFICATION_ID:
        raise ValueError("controlled recovery must use the exact V2 D0 qualification")
    if sha256(qualification_bytes).hexdigest() != qualification_id:
        raise ValueError("D0 qualification report is not content-addressed")
    registry = load_d0_source_registry(
        source_registry_path, repository_root / "configs/assets/etf_universe_v2.yaml"
    )
    registry_sha256 = sha256(source_registry_path.read_bytes()).hexdigest()
    if config_hashes.get(registry_relative) != registry_sha256:
        raise ValueError("source registry hash differs from the frozen experiment")
    if qualification.get("source_registry_sha256") != registry_sha256:
        raise ValueError("D0 qualification and source registry hashes differ")
    qualified_assets = {
        item["symbol"]: item
        for item in qualification.get("assets", [])
        if isinstance(item, dict) and isinstance(item.get("symbol"), str)
    }
    assets: list[LockedAssetInput] = []
    for selection in registry.assets:
        qualified = qualified_assets.get(selection.symbol)
        if qualified is None or qualified.get("result") != "QUALIFIED":
            raise ValueError(f"D0 asset is not qualified: {selection.symbol}")
        if qualified.get("raw_manifest_id") != selection.canonical_raw_manifest_id:
            raise ValueError("D0 raw source differs from the frozen source registry")
        causal_id = qualified.get("causal_manifest_id")
        ledger_sha = qualified.get("ledger_sha256")
        reproduction_id = qualified.get("deterministic_reproduction_report_id")
        if not all(isinstance(item, str) for item in (causal_id, ledger_sha, reproduction_id)):
            raise ValueError("D0 qualification lacks causal reproduction identities")
        assert isinstance(causal_id, str)
        assert isinstance(ledger_sha, str)
        assert isinstance(reproduction_id, str)
        ledger_path = repository_root / "configs/corporate_actions" / f"{selection.symbol}_v1.yaml"
        if sha256(ledger_path.read_bytes()).hexdigest() != ledger_sha:
            raise ValueError(f"corporate-action ledger changed after D0: {selection.symbol}")
        reproduction_path = (
            qualification_path.parent.parent
            / "reproductions"
            / reproduction_id
            / "causal_reproduction.json"
        )
        if (
            not reproduction_path.is_file()
            or sha256(reproduction_path.read_bytes()).hexdigest() != reproduction_id
        ):
            raise ValueError(f"D0 reproduction receipt is invalid: {selection.symbol}")
        causal = _load_causal_manifest(data_root, causal_id, selection.canonical_raw_manifest_id)
        raw_sha = _raw_normalized_sha256(data_root, selection.canonical_raw_manifest_id)
        assets.append(
            LockedAssetInput(
                symbol=selection.symbol,
                exchange=selection.exchange.value,
                raw_manifest_id=selection.canonical_raw_manifest_id,
                raw_normalized_sha256=raw_sha,
                causal_manifest_id=causal.manifest_id,
                causal_output_sha256=causal.output_file.sha256,
                ledger_sha256=ledger_sha,
                reproduction_report_id=reproduction_id,
            )
        )
    assets.sort(key=lambda item: item.symbol)
    experiment_relative = experiment_path.relative_to(repository_root).as_posix()
    output_relative = output_path.relative_to(repository_root).as_posix()
    data_snapshot_id = _hash_json([asdict(asset) for asset in assets])
    if recovery is not None and data_snapshot_id != V2_DATA_SNAPSHOT_ID:
        raise ValueError("controlled recovery must use the exact V2 data snapshot")
    version = RECOVERY_PRECOMMIT_VERSION if recovery is not None else PRECOMMIT_VERSION
    status = "CONTROLLED_RECOVERY_PRECOMMIT" if recovery is not None else "LOCKED_TEST_PRECOMMIT"
    payload: dict[str, object] = {
        "version": version,
        "status": status,
        "experiment_id": _string(experiment, "experiment_id"),
        "code_commit": _git(repository_root, "rev-parse", "HEAD"),
        "tracked_tree_sha256": _tracked_tree_sha256(repository_root, output_relative),
        "data_snapshot_id": data_snapshot_id,
        "qualification_report_id": qualification_id,
        "qualification_report_sha256": sha256(qualification_bytes).hexdigest(),
        "source_registry_sha256": registry_sha256,
        "source_registry_path": registry_relative,
        "experiment_config_path": experiment_relative,
        "experiment_config_sha256": sha256(experiment_path.read_bytes()).hexdigest(),
        "config_hashes": config_hashes,
        "walk_forward_split_sha256": _hash_json(experiment.get("walk_forward_splits")),
        "selection_period_end": _date_string(experiment, "selection_period_end"),
        "locked_test_start": _date_string(experiment, "locked_test_start"),
        "locked_test_end": _date_string(experiment, "locked_test_end"),
        "last_locked_signal_date": _date_string(experiment, "last_locked_signal_date"),
        "random_seed": _integer(experiment, "random_seed"),
        "assets": [asdict(asset) for asset in assets],
        "protocol_mode": RECOVERY_MODE if recovery is not None else "fresh_holdout",
        "predecessor_precommit_id": V2_PRECOMMIT_ID if recovery is not None else None,
        "predecessor_attempt_sha256": V2_ATTEMPT_SHA256 if recovery is not None else None,
        "predecessor_failure_sha256": V2_FAILURE_SHA256 if recovery is not None else None,
        "predecessor_precommit_file_sha256": (
            V2_PRECOMMIT_FILE_SHA256 if recovery is not None else None
        ),
        "run_plan_names": _recovery_run_names(experiment) if recovery is not None else [],
        "holdout_status": "NOT_FRESH_PREVIOUSLY_ACCESSED" if recovery is not None else "FRESH",
        "authorized_builds": ["build_a", "build_b"] if recovery is not None else ["build_a"],
        "retry_count": 0,
    }
    precommit_id = _hash_json(payload)
    return LockedTestPrecommit(
        precommit_id=precommit_id,
        version=version,
        status=status,
        experiment_id=_string(experiment, "experiment_id"),
        code_commit=_git(repository_root, "rev-parse", "HEAD"),
        tracked_tree_sha256=cast(str, payload["tracked_tree_sha256"]),
        data_snapshot_id=cast(str, payload["data_snapshot_id"]),
        qualification_report_id=qualification_id,
        qualification_report_sha256=sha256(qualification_bytes).hexdigest(),
        source_registry_sha256=registry_sha256,
        source_registry_path=registry_relative,
        experiment_config_path=experiment_relative,
        experiment_config_sha256=sha256(experiment_path.read_bytes()).hexdigest(),
        config_hashes=config_hashes,
        walk_forward_split_sha256=cast(str, payload["walk_forward_split_sha256"]),
        selection_period_end=_date_string(experiment, "selection_period_end"),
        locked_test_start=_date_string(experiment, "locked_test_start"),
        locked_test_end=_date_string(experiment, "locked_test_end"),
        last_locked_signal_date=_date_string(experiment, "last_locked_signal_date"),
        random_seed=_integer(experiment, "random_seed"),
        assets=tuple(assets),
        protocol_mode=cast(str, payload["protocol_mode"]),
        predecessor_precommit_id=cast(str | None, payload["predecessor_precommit_id"]),
        predecessor_attempt_sha256=cast(str | None, payload["predecessor_attempt_sha256"]),
        predecessor_failure_sha256=cast(str | None, payload["predecessor_failure_sha256"]),
        predecessor_precommit_file_sha256=cast(
            str | None, payload["predecessor_precommit_file_sha256"]
        ),
        run_plan_names=tuple(cast(list[str], payload["run_plan_names"])),
        holdout_status=cast(str, payload["holdout_status"]),
        authorized_builds=tuple(cast(list[str], payload["authorized_builds"])),
        retry_count=0,
    )


def persist_locked_test_precommit(precommit: LockedTestPrecommit, output_path: Path) -> Path:
    """Write one immutable precommit whose ID covers every field except itself."""
    write_immutable(output_path, _json_bytes(precommit.as_dict()) + b"\n")
    return output_path


def verify_locked_test_precommit(
    precommit_path: Path,
    repository_root: Path,
    data_root: Path,
    qualification_path: Path,
    *,
    before_data_read: Callable[[LockedTestPrecommit], None] | None = None,
) -> LockedTestPrecommit:
    """Revalidate every frozen code, config, D0, raw, causal, and split identity."""
    payload = json.loads(precommit_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("locked-test precommit must be a JSON object")
    assets_payload = payload.get("assets")
    if not isinstance(assets_payload, list):
        raise ValueError("locked-test precommit must declare assets")
    precommit = LockedTestPrecommit(
        **{
            **payload,
            "assets": tuple(LockedAssetInput(**item) for item in assets_payload),
            "run_plan_names": tuple(payload.get("run_plan_names", ())),
            "authorized_builds": tuple(payload.get("authorized_builds", ("build_a",))),
        }
    )
    recovery_precommit = precommit.protocol_mode == RECOVERY_MODE
    if recovery_precommit:
        _validate_recovery_precommit_identity(precommit)
    else:
        reject_consumed_holdout(precommit.locked_test_start, precommit.locked_test_end)
    expected_identity = (
        (RECOVERY_PRECOMMIT_VERSION, "CONTROLLED_RECOVERY_PRECOMMIT")
        if recovery_precommit
        else (PRECOMMIT_VERSION, "LOCKED_TEST_PRECOMMIT")
    )
    if (precommit.version, precommit.status) != expected_identity:
        raise ValueError("locked-test precommit has an unsupported version or status")
    identity = precommit.as_dict()
    identity.pop("precommit_id")
    if _hash_json(identity) != precommit.precommit_id:
        raise ValueError("locked-test precommit identity mismatch")
    _require_clean_tracked_tree(repository_root)
    relative = precommit_path.relative_to(repository_root).as_posix()
    head = _git(repository_root, "rev-parse", "HEAD")
    if head != precommit.code_commit:
        commit_count = int(
            _git(repository_root, "rev-list", "--count", f"{precommit.code_commit}..{head}")
        )
        changed = _git(
            repository_root, "diff", "--name-only", f"{precommit.code_commit}..{head}"
        ).splitlines()
        if commit_count != 1 or changed != [relative]:
            raise ValueError("HEAD must be the single precommit commit above frozen code")
    if _tracked_tree_sha256(repository_root, relative) != precommit.tracked_tree_sha256:
        raise ValueError("tracked research tree changed after locked-test precommit")
    experiment_path = repository_root / precommit.experiment_config_path
    if sha256(experiment_path.read_bytes()).hexdigest() != precommit.experiment_config_sha256:
        raise ValueError("locked experiment config changed after precommit")
    experiment = load_preregistered_experiment(experiment_path)
    recovery = _controlled_recovery(experiment)
    if recovery_precommit != (recovery is not None):
        raise ValueError("experiment and precommit recovery modes differ")
    if recovery is not None:
        if (
            precommit.experiment_config_path != V3_EXPERIMENT_PATH
            or precommit.experiment_config_sha256 != V3_EXPERIMENT_SHA256
            or precommit.qualification_report_id != V2_QUALIFICATION_ID
        ):
            raise ValueError("controlled recovery inputs differ from the V3 authorization")
        _verify_recovery_runtime(experiment)
    verify_declared_config_hashes(experiment, repository_root)
    expected_config_hashes = _string_mapping(
        experiment.get("frozen_config_sha256"), "config hashes"
    )
    if precommit.config_hashes != expected_config_hashes:
        raise ValueError("precommit config hashes differ from the frozen experiment")
    expected_fields: tuple[tuple[str, object], ...] = (
        ("experiment_id", _string(experiment, "experiment_id")),
        ("selection_period_end", _date_string(experiment, "selection_period_end")),
        ("locked_test_start", _date_string(experiment, "locked_test_start")),
        ("locked_test_end", _date_string(experiment, "locked_test_end")),
        ("last_locked_signal_date", _date_string(experiment, "last_locked_signal_date")),
        ("random_seed", _integer(experiment, "random_seed")),
    )
    if any(getattr(precommit, field) != expected for field, expected in expected_fields):
        raise ValueError("precommit fields differ from the frozen experiment")
    if _string(experiment, "source_registry_path") != precommit.source_registry_path:
        raise ValueError("experiment source registry path differs from the precommit")
    registry_path = (repository_root / precommit.source_registry_path).resolve()
    if sha256(registry_path.read_bytes()).hexdigest() != precommit.source_registry_sha256:
        raise ValueError("source registry changed after precommit")
    registry = load_d0_source_registry(
        registry_path, repository_root / "configs/assets/etf_universe_v2.yaml"
    )
    selections = {(item.symbol, item.exchange.value): item for item in registry.assets}
    frozen_assets = {(item.symbol, item.exchange): item for item in precommit.assets}
    if set(selections) != set(frozen_assets):
        raise ValueError("source registry asset set differs from the precommit")
    if any(
        selections[identity].canonical_raw_manifest_id != asset.raw_manifest_id
        for identity, asset in frozen_assets.items()
    ):
        raise ValueError("source registry raw selection differs from the precommit")
    if _hash_json(experiment.get("walk_forward_splits")) != precommit.walk_forward_split_sha256:
        raise ValueError("walk-forward split changed after precommit")
    qualification_bytes = qualification_path.read_bytes()
    if (
        qualification_path.parent.name != precommit.qualification_report_id
        or sha256(qualification_bytes).hexdigest() != precommit.qualification_report_sha256
        or precommit.qualification_report_id != precommit.qualification_report_sha256
    ):
        raise ValueError("D0 qualification changed after precommit")
    qualification = json.loads(qualification_bytes)
    if (
        not isinstance(qualification, dict)
        or qualification.get("all_qualified") is not True
        or qualification.get("source_registry_sha256") != precommit.source_registry_sha256
    ):
        raise ValueError("precommit qualification is not valid for the frozen source registry")
    qualified_assets = {
        item["symbol"]: item
        for item in qualification.get("assets", [])
        if isinstance(item, dict) and isinstance(item.get("symbol"), str)
    }
    if precommit.data_snapshot_id != _hash_json([asdict(asset) for asset in precommit.assets]):
        raise ValueError("precommit data snapshot identity mismatch")
    if recovery_precommit:
        _verify_v2_failure_archive(repository_root)
    if before_data_read is not None:
        before_data_read(precommit)
    for asset in precommit.assets:
        qualified = qualified_assets.get(asset.symbol)
        if (
            qualified is None
            or qualified.get("result") != "QUALIFIED"
            or qualified.get("raw_manifest_id") != asset.raw_manifest_id
            or qualified.get("causal_manifest_id") != asset.causal_manifest_id
            or qualified.get("ledger_sha256") != asset.ledger_sha256
            or qualified.get("deterministic_reproduction_report_id") != asset.reproduction_report_id
        ):
            raise ValueError(f"precommit asset differs from D0 qualification: {asset.symbol}")
        ledger_path = repository_root / "configs/corporate_actions" / f"{asset.symbol}_v1.yaml"
        if sha256(ledger_path.read_bytes()).hexdigest() != asset.ledger_sha256:
            raise ValueError(f"corporate-action ledger changed after precommit: {asset.symbol}")
        if _raw_normalized_sha256(data_root, asset.raw_manifest_id) != asset.raw_normalized_sha256:
            raise ValueError(f"raw input changed after precommit: {asset.symbol}")
        causal = _load_causal_manifest(data_root, asset.causal_manifest_id, asset.raw_manifest_id)
        if causal.output_file.sha256 != asset.causal_output_sha256:
            raise ValueError(f"causal input changed after precommit: {asset.symbol}")
    return precommit


def verify_controlled_recovery_authorization(
    precommit_path: Path, repository_root: Path
) -> LockedTestPrecommit:
    """Verify the V3 authorization and frozen code/config identity without reading prices."""
    payload = json.loads(precommit_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("assets"), list):
        raise ValueError("controlled recovery authorization must be a JSON object with assets")
    precommit = LockedTestPrecommit(
        **{
            **payload,
            "assets": tuple(LockedAssetInput(**item) for item in payload["assets"]),
            "run_plan_names": tuple(payload.get("run_plan_names", ())),
            "authorized_builds": tuple(payload.get("authorized_builds", ())),
        }
    )
    if (
        precommit.version != RECOVERY_PRECOMMIT_VERSION
        or precommit.status != "CONTROLLED_RECOVERY_PRECOMMIT"
        or precommit.protocol_mode != RECOVERY_MODE
    ):
        raise ValueError("unsupported controlled recovery authorization identity")
    identity = precommit.as_dict()
    identity.pop("precommit_id")
    if _hash_json(identity) != precommit.precommit_id:
        raise ValueError("controlled recovery authorization content hash mismatch")
    _validate_recovery_precommit_identity(precommit)
    expected_path = repository_root.resolve() / V3_AUTHORIZATION_PATH
    if precommit_path.resolve() != expected_path:
        raise ValueError("controlled recovery authorization path is not canonical")
    _require_clean_tracked_tree(repository_root)
    head = _git(repository_root, "rev-parse", "HEAD")
    if head != precommit.code_commit:
        commits = int(
            _git(repository_root, "rev-list", "--count", f"{precommit.code_commit}..{head}")
        )
        changed = _git(
            repository_root, "diff", "--name-only", f"{precommit.code_commit}..{head}"
        ).splitlines()
        if commits != 1 or changed != [V3_AUTHORIZATION_PATH]:
            raise ValueError("HEAD must contain only the V3 authorization above frozen code")
    if (
        _tracked_tree_sha256(repository_root, V3_AUTHORIZATION_PATH)
        != precommit.tracked_tree_sha256
    ):
        raise ValueError("tracked research tree changed after V3 authorization")
    experiment_path = repository_root / V3_EXPERIMENT_PATH
    if (
        sha256(experiment_path.read_bytes()).hexdigest() != V3_EXPERIMENT_SHA256
        or precommit.experiment_config_path != V3_EXPERIMENT_PATH
        or precommit.experiment_config_sha256 != V3_EXPERIMENT_SHA256
    ):
        raise ValueError("V3 experiment differs from its frozen authorization")
    experiment = load_preregistered_experiment(experiment_path)
    _controlled_recovery(experiment)
    verify_declared_config_hashes(experiment, repository_root)
    expected_hashes = _string_mapping(experiment.get("frozen_config_sha256"), "config hashes")
    if precommit.config_hashes != expected_hashes:
        raise ValueError("V3 authorization configuration hashes differ")
    expected_fields = (
        (precommit.experiment_id, _string(experiment, "experiment_id")),
        (precommit.selection_period_end, _date_string(experiment, "selection_period_end")),
        (precommit.locked_test_start, _date_string(experiment, "locked_test_start")),
        (precommit.locked_test_end, _date_string(experiment, "locked_test_end")),
        (precommit.last_locked_signal_date, _date_string(experiment, "last_locked_signal_date")),
        (precommit.random_seed, _integer(experiment, "random_seed")),
        (precommit.walk_forward_split_sha256, _hash_json(experiment["walk_forward_splits"])),
    )
    if any(observed != expected for observed, expected in expected_fields):
        raise ValueError("V3 authorization fields differ from its experiment")
    qualification = (
        repository_root
        / "artifacts/data_qualification"
        / V2_QUALIFICATION_ID
        / "qualification.json"
    )
    if (
        not qualification.is_file()
        or sha256(qualification.read_bytes()).hexdigest() != V2_QUALIFICATION_ID
        or precommit.qualification_report_sha256 != V2_QUALIFICATION_ID
    ):
        raise ValueError("V3 authorization D0 report identity mismatch")
    if precommit.data_snapshot_id != _hash_json([asdict(asset) for asset in precommit.assets]):
        raise ValueError("V3 authorization asset snapshot identity mismatch")
    _verify_v2_failure_archive(repository_root)
    return precommit


def _load_causal_manifest(
    data_root: Path, manifest_id: str, source_manifest_id: str
) -> CanonicalDatasetManifest:
    path = data_root / "canonical" / "manifests" / f"{manifest_id}.json"
    manifest = CanonicalDatasetManifest.model_validate_json(path.read_text(encoding="utf-8"))
    if (
        manifest.price_basis is not PriceBasis.CAUSAL_ADJUSTED
        or manifest.source_manifest_ids != (source_manifest_id,)
        or path.stem != manifest.manifest_id
    ):
        raise ValueError("causal manifest does not match the frozen raw source")
    output = data_root / manifest.output_file.relative_path
    if (
        not output.is_file()
        or sha256(output.read_bytes()).hexdigest() != manifest.output_file.sha256
    ):
        raise ValueError("causal output does not match its manifest")
    return manifest


def _raw_normalized_sha256(data_root: Path, manifest_id: str) -> str:
    paths = (
        data_root / "manifests" / f"{manifest_id}.json",
        data_root / "manifests" / "providers" / f"{manifest_id}.json",
    )
    path = next((candidate for candidate in paths if candidate.is_file()), None)
    if path is None:
        raise ValueError(f"raw provider manifest is missing: {manifest_id}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    normalized = payload.get("normalized_file") if isinstance(payload, dict) else None
    if not isinstance(normalized, dict) or not isinstance(normalized.get("sha256"), str):
        raise ValueError("raw provider manifest lacks a normalized SHA-256")
    relative = normalized.get("relative_path")
    expected = normalized.get("sha256")
    if not isinstance(relative, str) or not isinstance(expected, str):
        raise ValueError("raw provider manifest lacks a normalized path")
    output = data_root / relative
    if not output.is_file() or sha256(output.read_bytes()).hexdigest() != expected:
        raise ValueError("raw normalized artifact does not match its manifest")
    return expected


def _tracked_tree_sha256(repository_root: Path, excluded_relative: str) -> str:
    paths = _git(repository_root, "ls-files", "-z").split("\0")
    entries = []
    for relative in sorted(item for item in paths if item and item != excluded_relative):
        path = repository_root / relative
        entries.append({"path": relative, "sha256": sha256(path.read_bytes()).hexdigest()})
    return _hash_json(entries)


def _require_clean_tracked_tree(repository_root: Path) -> None:
    status = _git(repository_root, "status", "--porcelain", "--untracked-files=all")
    for line in status.splitlines():
        if line.startswith("?? ") and _allowed_untracked(line[3:]):
            continue
        raise ValueError("research Git tree must be clean before locked-test operations")


def _allowed_untracked(relative: str) -> bool:
    """Allow only data, result, environment, and tool-cache paths outside the code tree."""
    prefixes = (
        "data/",
        "artifacts/",
        ".conda/",
        ".venv/",
        ".mypy_cache/",
        ".pytest_cache/",
        ".ruff_cache/",
        "htmlcov/",
    )
    return relative == ".coverage" or relative.startswith(prefixes)


def _git(repository_root: Path, *arguments: str) -> str:
    return str(subprocess.check_output(("git", *arguments), cwd=repository_root, text=True)).strip()


def _string(mapping: dict[str, object], field: str) -> str:
    value = mapping.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"experiment requires {field}")
    return value


def _date_string(mapping: dict[str, object], field: str) -> str:
    value = mapping.get(field)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        return date.fromisoformat(value).isoformat()
    raise ValueError(f"experiment requires {field}")


def _integer(mapping: dict[str, object], field: str) -> int:
    value = mapping.get(field)
    if not isinstance(value, int):
        raise ValueError(f"experiment requires integer {field}")
    return value


def _string_mapping(value: object, name: str) -> dict[str, str]:
    if not isinstance(value, dict) or any(
        not isinstance(key, str) or not isinstance(item, str) for key, item in value.items()
    ):
        raise ValueError(f"experiment requires {name}")
    return dict(value)


def _hash_json(value: object) -> str:
    return sha256(_json_bytes(value)).hexdigest()


def _json_bytes(value: object) -> bytes:
    return canonical_json(value)


def reject_consumed_holdout(start: str, end: str) -> None:
    """Preserve the consumed V2 interval across code, snapshot and precommit ID changes."""
    if date.fromisoformat(start) <= date(2026, 9, 9) and date.fromisoformat(end) >= date(
        2024, 1, 2
    ):
        raise ValueError("V2 holdout interval is consumed; a new research protocol is required")


def _controlled_recovery(experiment: dict[str, object]) -> dict[str, object] | None:
    """Validate the one explicitly authorized V3 predecessor and return its declaration."""
    if experiment.get("protocol_mode") != RECOVERY_MODE:
        return None
    recovery = experiment.get("controlled_recovery")
    expected: dict[str, object] = {
        "predecessor_precommit_id": V2_PRECOMMIT_ID,
        "predecessor_precommit_file_sha256": V2_PRECOMMIT_FILE_SHA256,
        "predecessor_attempt_sha256": V2_ATTEMPT_SHA256,
        "predecessor_failure_sha256": V2_FAILURE_SHA256,
        "predecessor_data_snapshot_id": V2_DATA_SNAPSHOT_ID,
        "authorized_builds": ["build_a", "build_b"],
        "require_prepared_bytes_equal": True,
        "publish_build": "build_a",
        "parent_attempt_limit": 1,
        "retry_count": 0,
        "evidence_scope": "CONTROLLED_RECOVERY_RESEARCH",
        "holdout_status": "NOT_FRESH_PREVIOUSLY_ACCESSED",
    }
    if recovery != expected:
        raise ValueError("controlled recovery declaration differs from the V3 authorization")
    if (
        _date_string(experiment, "locked_test_start") != "2024-01-02"
        or _date_string(experiment, "locked_test_end") != "2026-09-09"
        or _date_string(experiment, "last_locked_signal_date") != "2026-08-31"
    ):
        raise ValueError("controlled recovery dates differ from the authorized V2 interval")
    _recovery_run_names(experiment)
    return expected


def _validate_recovery_precommit_identity(precommit: LockedTestPrecommit) -> None:
    """Reject any widened or relabelled consumed-interval recovery precommit."""
    if (
        precommit.predecessor_precommit_id != V2_PRECOMMIT_ID
        or precommit.predecessor_attempt_sha256 != V2_ATTEMPT_SHA256
        or precommit.predecessor_failure_sha256 != V2_FAILURE_SHA256
        or precommit.predecessor_precommit_file_sha256 != V2_PRECOMMIT_FILE_SHA256
        or precommit.data_snapshot_id != V2_DATA_SNAPSHOT_ID
        or precommit.locked_test_start != "2024-01-02"
        or precommit.locked_test_end != "2026-09-09"
        or precommit.last_locked_signal_date != "2026-08-31"
        or precommit.selection_period_end != "2023-12-29"
        or precommit.walk_forward_split_sha256 != V2_WALK_FORWARD_SPLIT_SHA256
        or precommit.qualification_report_id != V2_QUALIFICATION_ID
        or precommit.random_seed != 0
        or precommit.run_plan_names != tuple(_AUTHORIZED_RECOVERY_RUNS)
        or precommit.holdout_status != "NOT_FRESH_PREVIOUSLY_ACCESSED"
        or precommit.authorized_builds != ("build_a", "build_b")
        or precommit.retry_count != 0
    ):
        raise ValueError("controlled recovery precommit exceeds its explicit authorization")


def _verify_v2_failure_archive(repository_root: Path) -> None:
    """Bind V3 to the preserved V2 attempt and failure bytes before market-data access."""
    root = repository_root / "artifacts" / "issue009" / "locked_runs" / V2_PRECOMMIT_ID
    expected = (("attempt.json", V2_ATTEMPT_SHA256), ("failure.json", V2_FAILURE_SHA256))
    for filename, digest in expected:
        path = root / filename
        if not path.is_file() or sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f"archived V2 {filename} does not match the recovery contract")
    precommit_path = repository_root / "configs/experiments/LOCKED_TEST_PRECOMMIT_V2.json"
    if sha256(precommit_path.read_bytes()).hexdigest() != V2_PRECOMMIT_FILE_SHA256:
        raise ValueError("archived V2 precommit file does not match the recovery contract")


_AUTHORIZED_RECOVERY_RUNS = [
    *(f"WALK_FORWARD_BASE_FOLD_{index}" for index in range(1, 7)),
    "LOCKED_BASE_T1",
    "LOCKED_DOUBLE_COST_T1",
    "LOCKED_BASE_T2",
    "LOCKED_NEIGHBOR_M3_N1",
    "LOCKED_NEIGHBOR_M3_N2",
    "LOCKED_NEIGHBOR_M6_N1",
    "LOCKED_NEIGHBOR_M6_N2",
    "LOCKED_NEIGHBOR_M12_N1",
    "LOCKED_START_TRIM_21",
    "LOCKED_END_TRIM_21",
]


def _recovery_run_names(experiment: dict[str, object]) -> list[str]:
    value = experiment.get("ordered_run_names")
    if value != _AUTHORIZED_RECOVERY_RUNS:
        raise ValueError("controlled recovery ordered run plan differs from authorization")
    return list(_AUTHORIZED_RECOVERY_RUNS)


def _verify_recovery_runtime(experiment: dict[str, object]) -> None:
    """Require the exact preregistered runtime identity for both deterministic builds."""
    declared = experiment.get("runtime_environment")
    observed = {
        "python": platform.python_version(),
        "pandas": pd.__version__,
        "numpy": np.__version__,
        "pyarrow": pyarrow.__version__,
        "pythonhashseed": os.environ.get("PYTHONHASHSEED", "UNSET"),
        "timezone": os.environ.get("TZ", "UNSET"),
        "omp_num_threads": os.environ.get("OMP_NUM_THREADS", "UNSET"),
        "openblas_num_threads": os.environ.get("OPENBLAS_NUM_THREADS", "UNSET"),
        "mkl_num_threads": os.environ.get("MKL_NUM_THREADS", "UNSET"),
        "numexpr_num_threads": os.environ.get("NUMEXPR_NUM_THREADS", "UNSET"),
    }
    if declared != observed:
        raise ValueError(f"controlled recovery runtime mismatch: observed {observed}")
