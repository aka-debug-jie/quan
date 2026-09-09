from datetime import UTC, datetime
from pathlib import Path

import pytest

from quant_stack.snapshot import create_raw_snapshot, write_immutable


def test_immutable_file_allows_identical_retry(tmp_path: Path) -> None:
    destination = tmp_path / "raw" / "bars.csv"
    write_immutable(destination, b"first")
    write_immutable(destination, b"first")
    assert destination.read_bytes() == b"first"


def test_immutable_file_rejects_changed_content(tmp_path: Path) -> None:
    destination = tmp_path / "raw" / "bars.csv"
    write_immutable(destination, b"first")
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        write_immutable(destination, b"second")
    assert destination.read_bytes() == b"first"


def test_snapshot_is_content_addressed(tmp_path: Path) -> None:
    source = tmp_path / "input.csv"
    source.write_bytes(b"symbol,trading_date\nSYNTH_A,2024-01-02\n")
    created_at = datetime(2024, 1, 3, tzinfo=UTC)

    snapshot_path, manifest = create_raw_snapshot(
        tmp_path / "raw", source, source="test-fixture", created_at=created_at
    )

    assert snapshot_path.parent.name == manifest.snapshot_id
    assert manifest.files[0].sha256 == manifest.snapshot_id
    assert snapshot_path.read_bytes() == source.read_bytes()
    assert (snapshot_path.parent / "manifest.json").is_file()


def test_identical_snapshot_retry_reuses_original_manifest(tmp_path: Path) -> None:
    source = tmp_path / "input.csv"
    source.write_bytes(b"symbol,trading_date\nSYNTH_A,2024-01-02\n")
    first_time = datetime(2024, 1, 3, tzinfo=UTC)
    later_time = datetime(2024, 2, 3, tzinfo=UTC)

    first_path, first_manifest = create_raw_snapshot(
        tmp_path / "raw", source, source="test-fixture", created_at=first_time
    )
    retry_path, retry_manifest = create_raw_snapshot(
        tmp_path / "raw", source, source="test-fixture", created_at=later_time
    )

    assert retry_path == first_path
    assert retry_manifest == first_manifest
    assert retry_manifest.created_at == first_time
