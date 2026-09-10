"""Issue 009 V2 precommit creation and single-use locked-test execution."""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import cast

from quant_stack.d0_inventory import load_d0_source_registry
from quant_stack.data.models import CanonicalDatasetManifest
from quant_stack.models import PriceBasis
from quant_stack.snapshot import write_immutable
from quant_stack.walk_forward import (
    load_preregistered_experiment,
    verify_declared_config_hashes,
)

PRECOMMIT_VERSION = "1.0.0"


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
    payload: dict[str, object] = {
        "version": PRECOMMIT_VERSION,
        "status": "LOCKED_TEST_PRECOMMIT",
        "experiment_id": _string(experiment, "experiment_id"),
        "code_commit": _git(repository_root, "rev-parse", "HEAD"),
        "tracked_tree_sha256": _tracked_tree_sha256(repository_root, output_relative),
        "data_snapshot_id": _hash_json([asdict(asset) for asset in assets]),
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
    }
    precommit_id = _hash_json(payload)
    return LockedTestPrecommit(
        precommit_id=precommit_id,
        version=PRECOMMIT_VERSION,
        status="LOCKED_TEST_PRECOMMIT",
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
) -> LockedTestPrecommit:
    """Revalidate every frozen code, config, D0, raw, causal, and split identity."""
    payload = json.loads(precommit_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("locked-test precommit must be a JSON object")
    assets_payload = payload.get("assets")
    if not isinstance(assets_payload, list):
        raise ValueError("locked-test precommit must declare assets")
    precommit = LockedTestPrecommit(
        **{**payload, "assets": tuple(LockedAssetInput(**item) for item in assets_payload)}
    )
    if precommit.version != PRECOMMIT_VERSION or precommit.status != "LOCKED_TEST_PRECOMMIT":
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
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode()
