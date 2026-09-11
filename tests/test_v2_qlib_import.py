"""Offline safety and qualification tests for V2 Qlib archive import."""

from __future__ import annotations

import io
import json
import tarfile
from datetime import date
from hashlib import sha256
from pathlib import Path

import pytest

from quant_stack_v2.pit import build_pit_universe, qualify_pit_universe
from quant_stack_v2.qlib_import import QlibImportError, QlibInstrumentInterval, import_qlib_archive


def _archive(path: Path, *, missing_factor: bool = False, unsafe: bool = False) -> None:
    files = {
        "fixture/calendars/day.txt": b"2020-01-01\n2020-01-02\n",
        "fixture/instruments/csi300.txt": b"sh000001\t2020-01-01\t2020-01-02\n",
        "fixture/instruments/csi500.txt": b"sz000002\t2020-01-01\t2020-01-02\n",
        "fixture/features/sh000001/open.day.bin": b"open",
        "fixture/features/sh000001/close.day.bin": b"close",
        "fixture/features/sh000001/factor.day.bin": b"factor",
        "fixture/features/sz000002/open.day.bin": b"open",
        "fixture/features/sz000002/close.day.bin": b"close",
        "fixture/features/sz000002/factor.day.bin": b"factor",
    }
    if missing_factor:
        files.pop("fixture/features/sz000002/factor.day.bin")
    if unsafe:
        files["../escape.txt"] = b"unsafe"
    with tarfile.open(path, "w:gz") as archive:
        for name, content in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))


def _manifest(path: Path) -> None:
    path.write_text(json.dumps({"release_tag": "fixture"}), encoding="utf-8")


def test_import_is_hash_checked_safe_and_deterministic(tmp_path: Path) -> None:
    archive, manifest = tmp_path / "qlib.tar.gz", tmp_path / "manifest.json"
    _archive(archive)
    _manifest(manifest)
    archive_hash = sha256(archive.read_bytes()).hexdigest()
    manifest_hash = sha256(manifest.read_bytes()).hexdigest()
    first_path, first = import_qlib_archive(
        archive,
        manifest,
        tmp_path / "artifacts/v2",
        expected_archive_sha256=archive_hash,
        expected_manifest_sha256=manifest_hash,
    )
    second_path, second = import_qlib_archive(
        archive,
        manifest,
        tmp_path / "artifacts/v2",
        expected_archive_sha256=archive_hash,
        expected_manifest_sha256=manifest_hash,
    )
    assert first_path == second_path
    assert first.identity_sha256 == second.identity_sha256
    assert first.status == "BLOCKED_DATA"
    assert first.csi300_intervals[0].symbol == "sh000001"


def test_import_rejects_hash_mismatch_and_unsafe_tar(tmp_path: Path) -> None:
    archive, manifest = tmp_path / "qlib.tar.gz", tmp_path / "manifest.json"
    _archive(archive, unsafe=True)
    _manifest(manifest)
    with pytest.raises(QlibImportError, match="unsafe"):
        import_qlib_archive(
            archive,
            manifest,
            tmp_path / "out",
            expected_archive_sha256=sha256(archive.read_bytes()).hexdigest(),
            expected_manifest_sha256=sha256(manifest.read_bytes()).hexdigest(),
        )
    with pytest.raises(QlibImportError, match="pinned SHA"):
        import_qlib_archive(
            archive,
            manifest,
            tmp_path / "out",
            expected_archive_sha256="0" * 64,
            expected_manifest_sha256=sha256(manifest.read_bytes()).hexdigest(),
        )


def test_import_reports_missing_factor_as_blocked_data(tmp_path: Path) -> None:
    archive, manifest = tmp_path / "qlib.tar.gz", tmp_path / "manifest.json"
    _archive(archive, missing_factor=True)
    _manifest(manifest)
    report_path, report = import_qlib_archive(
        archive,
        manifest,
        tmp_path / "out",
        expected_archive_sha256=sha256(archive.read_bytes()).hexdigest(),
        expected_manifest_sha256=sha256(manifest.read_bytes()).hexdigest(),
    )
    assert report_path.is_file()
    assert report.status == "BLOCKED_DATA"
    assert report.missing_price_or_factor_symbols == ("sz000002",)


def test_pit_membership_prevents_static_future_universe_and_rejects_overlap() -> None:
    intervals = (
        QlibInstrumentInterval("a", date(2020, 1, 1), date(2020, 1, 2)),
        QlibInstrumentInterval("b", date(2020, 1, 3), date(2020, 1, 4)),
    )
    universe = build_pit_universe("csi300", intervals)
    assert universe.members_on(date(2020, 1, 1)) == ("a",)
    assert universe.members_on(date(2020, 1, 3)) == ("b",)
    with pytest.raises(QlibImportError, match="overlap"):
        build_pit_universe(
            "csi300",
            (
                QlibInstrumentInterval("a", date(2020, 1, 1), date(2020, 1, 3)),
                QlibInstrumentInterval("a", date(2020, 1, 3), date(2020, 1, 4)),
            ),
        )


def test_pit_qualification_blocks_missing_source_symbol() -> None:
    universe = build_pit_universe(
        "csi500", (QlibInstrumentInterval("a", date(2020, 1, 1), date(2020, 1, 2)),)
    )
    report = qualify_pit_universe(
        universe,
        (date(2020, 1, 1), date(2020, 1, 2)),
        available_symbols=set(),
        source_import_report_sha256="a" * 64,
    )
    assert report.status == "BLOCKED_DATA"
    assert report.unexplained_sessions == ("missing_symbol:a",)
