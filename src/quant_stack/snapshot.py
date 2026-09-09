"""Content-addressed, immutable raw-data snapshots."""

from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from quant_stack.models import DataManifest, ManifestFile


def write_immutable(path: Path, content: bytes) -> None:
    """Publish bytes atomically once; allow identical retries but reject changed content."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary_path, path)
        except FileExistsError:
            if path.read_bytes() != content:
                raise FileExistsError(f"refusing to overwrite immutable file: {path}") from None
        _fsync_directory(path.parent)
    finally:
        temporary_path.unlink(missing_ok=True)


def _fsync_directory(path: Path) -> None:
    """Persist the directory entry after an immutable file has been linked into place."""
    descriptor = os.open(path, os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def create_raw_snapshot(
    raw_root: Path,
    source_path: Path,
    *,
    source: str,
    created_at: datetime | None = None,
) -> tuple[Path, DataManifest]:
    """Copy a local input into a content-addressed immutable raw snapshot."""
    content = source_path.read_bytes()
    digest = sha256(content).hexdigest()
    snapshot_dir = raw_root / digest
    snapshot_path = snapshot_dir / source_path.name
    write_immutable(snapshot_path, content)
    manifest_path = snapshot_dir / "manifest.json"
    if manifest_path.exists():
        existing = DataManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        expected_file = ManifestFile(
            relative_path=source_path.name,
            sha256=digest,
            size_bytes=len(content),
        )
        if (
            existing.snapshot_id != digest
            or existing.source != source
            or existing.files != (expected_file,)
        ):
            raise FileExistsError(
                f"existing snapshot manifest conflicts with requested provenance: {manifest_path}"
            )
        return snapshot_path, existing

    manifest = DataManifest(
        snapshot_id=digest,
        source=source,
        created_at=created_at or datetime.now(UTC),
        files=(
            ManifestFile(relative_path=source_path.name, sha256=digest, size_bytes=len(content)),
        ),
    )
    write_immutable(
        manifest_path,
        manifest.model_dump_json(indent=2).encode("utf-8") + b"\n",
    )
    return snapshot_path, manifest
