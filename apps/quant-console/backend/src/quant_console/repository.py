"""Verified access to immutable Console read-model snapshots."""

from __future__ import annotations

import json
from collections import OrderedDict
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import cast

import pyarrow.parquet as pq  # type: ignore[import-untyped]
from pydantic import JsonValue

from quant_console.models import ConsoleMode, SnapshotMeta
from quant_console.snapshot import SnapshotError

JsonObject = dict[str, JsonValue]


@dataclass(frozen=True)
class SnapshotView:
    """One verified immutable read model held in memory."""

    meta: SnapshotMeta
    overview: JsonObject
    studies: list[JsonObject]
    experiments: list[JsonObject]
    details: dict[str, JsonObject]
    signals: JsonObject
    prospective: JsonObject
    health: JsonObject
    evidence: dict[str, JsonObject]
    root: Path


class SnapshotRepository:
    """Small LRU repository keyed only by validated content identities."""

    def __init__(self, runtime: Path, *, cache_size: int = 4) -> None:
        self.runtime = runtime.resolve()
        self.cache_size = cache_size
        self._cache: OrderedDict[str, SnapshotView] = OrderedDict()

    def current_meta(self) -> SnapshotMeta:
        """Return the current published snapshot metadata."""
        pointer = _object(self.runtime / "current.json")
        snapshot_id = _digest(str(pointer.get("snapshot_id", "")))
        manifest = _object(self._snapshot_root(snapshot_id) / "manifest.json")
        return _meta(
            manifest,
            published_at=str(pointer.get("published_at", manifest["published_at"])),
        )

    def view(self, snapshot_id: str) -> SnapshotView:
        """Load and verify one immutable snapshot without consulting current."""
        identity = _digest(snapshot_id)
        cached = self._cache.get(identity)
        if cached is not None:
            self._cache.move_to_end(identity)
            return cached
        view = self._load(identity)
        self._cache[identity] = view
        self._cache.move_to_end(identity)
        while len(self._cache) > self.cache_size:
            self._cache.popitem(last=False)
        return view

    def runtime_status(self) -> JsonObject:
        """Return Console-only mutable status with no source paths."""
        current: str | None = None
        try:
            current = self.current_meta().snapshot_id
        except (OSError, ValueError, KeyError):
            pass
        refresh: JsonObject | None = None
        refresh_path = self.runtime / "last_refresh.json"
        if refresh_path.is_file():
            refresh = _object(refresh_path)
        return {
            "app_version": "1.5.0",
            "current_snapshot_id": current,
            "last_refresh": refresh,
        }

    def clear(self) -> None:
        """Clear only the process-local immutable view cache."""
        self._cache.clear()

    def _load(self, snapshot_id: str) -> SnapshotView:
        root = self._snapshot_root(snapshot_id)
        manifest = _object(root / "manifest.json")
        if str(manifest.get("snapshot_id")) != snapshot_id:
            raise SnapshotError("snapshot manifest identity mismatch")
        files = manifest.get("files")
        if not isinstance(files, dict):
            raise SnapshotError("snapshot file manifest missing")
        identity = {
            "schema_version": manifest.get("schema_version"),
            "adapter_version": manifest.get("adapter_version"),
            "mode": manifest.get("mode"),
            "files": files,
        }
        if sha256(_canonical(identity)).hexdigest() != snapshot_id:
            raise SnapshotError("snapshot content identity mismatch")
        for relative, expected in files.items():
            if not isinstance(relative, str) or not isinstance(expected, str):
                raise SnapshotError("invalid snapshot file manifest")
            path = _within(root, relative)
            if _sha256(path) != expected:
                raise SnapshotError(f"snapshot file hash mismatch: {path.name}")
        experiments_value = _array(root / "experiments.json")
        experiments = [_as_object(item) for item in experiments_value]
        artifact_ids = [str(item.get("artifact_id", "")) for item in experiments]
        if len(set(artifact_ids)) != len(artifact_ids):
            raise SnapshotError("duplicate experiment artifact identity")
        ledger_rows = pq.read_metadata(root / "ledger.parquet").num_rows
        if ledger_rows != len(experiments):
            raise SnapshotError("experiment ledger conflicts with JSON projection")
        return SnapshotView(
            meta=_meta(manifest),
            overview=_object(root / "overview.json"),
            studies=[_as_object(item) for item in _array(root / "studies.json")],
            experiments=experiments,
            details=_object_map(root / "details.json"),
            signals=_object(root / "signals.json"),
            prospective=_object(root / "prospective.json"),
            health=_object(root / "health.json"),
            evidence=_object_map(root / "evidence.json"),
            root=root,
        )

    def _snapshot_root(self, snapshot_id: str) -> Path:
        root = (self.runtime / "snapshots" / snapshot_id).resolve(strict=True)
        snapshots = (self.runtime / "snapshots").resolve(strict=True)
        if not root.is_relative_to(snapshots) or root.is_symlink() or not root.is_dir():
            raise SnapshotError("snapshot path is not an approved directory")
        return root


def load_series(view: SnapshotView, series_id: str) -> JsonObject:
    """Load one series whose opaque identity is listed by the snapshot."""
    identity = _digest(series_id)
    relative = f"series/{identity}.json"
    files = _object(view.root / "manifest.json").get("files")
    if not isinstance(files, dict) or relative not in files:
        raise KeyError(identity)
    return _object(_within(view.root, relative))


def _meta(manifest: JsonObject, *, published_at: str | None = None) -> SnapshotMeta:
    schema_version = manifest["schema_version"]
    if not isinstance(schema_version, int):
        raise SnapshotError("snapshot schema version is invalid")
    return SnapshotMeta(
        schema_version=schema_version,
        snapshot_id=str(manifest["snapshot_id"]),
        mode=ConsoleMode(str(manifest["mode"])),
        published_at=published_at or str(manifest["published_at"]),
        adapter_version=str(manifest["adapter_version"]),
    )


def _within(root: Path, relative: str) -> Path:
    if not relative or relative.startswith("/") or ".." in Path(relative).parts:
        raise SnapshotError("snapshot file path escapes approved root")
    candidate = root / relative
    if candidate.is_symlink():
        raise SnapshotError("snapshot file cannot be a symbolic link")
    path = candidate.resolve(strict=True)
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise SnapshotError("snapshot file is not an approved regular file")
    return path


def _object(path: Path) -> JsonObject:
    value = _json(path)
    if not isinstance(value, dict):
        raise SnapshotError(f"expected object: {path.name}")
    return value


def _object_map(path: Path) -> dict[str, JsonObject]:
    value = _object(path)
    return {str(key): _as_object(item) for key, item in value.items()}


def _array(path: Path) -> list[JsonValue]:
    value = _json(path)
    if not isinstance(value, list):
        raise SnapshotError(f"expected array: {path.name}")
    return value


def _as_object(value: JsonValue) -> JsonObject:
    if not isinstance(value, dict):
        raise SnapshotError("expected nested object")
    return value


def _json(path: Path) -> JsonValue:
    try:
        return cast(JsonValue, json.loads(path.read_bytes()))
    except (OSError, json.JSONDecodeError) as error:
        raise SnapshotError(f"cannot read snapshot component: {path.name}") from error


def _digest(value: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise SnapshotError("invalid content identity")
    return value


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
