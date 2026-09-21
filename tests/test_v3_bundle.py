"""Offline security and schema tests for the historical bundle adapter."""

from __future__ import annotations

import io
import tarfile
from hashlib import sha256
from pathlib import Path

import numpy as np
import pytest

from quant_stack_v3.bundle import REQUIRED_FILES, BundleError, extract_and_inspect

h5py = pytest.importorskip("h5py")


def _bundle(tmp_path: Path) -> Path:
    root = tmp_path / "source" / "bundle"
    root.mkdir(parents=True)
    dtype = np.dtype(
        [
            ("datetime", "i8"),
            ("open", "f8"),
            ("high", "f8"),
            ("low", "f8"),
            ("close", "f8"),
            ("volume", "f8"),
            ("total_turnover", "f8"),
            ("limit_up", "f8"),
            ("limit_down", "f8"),
        ]
    )
    with h5py.File(root / "stocks.h5", "w") as handle:
        handle.create_dataset("000001.XSHE", data=np.zeros(2, dtype=dtype))
    for name in (
        "dividends.h5",
        "ex_cum_factor.h5",
        "split_factor.h5",
        "st_stock_days.h5",
        "suspended_days.h5",
    ):
        with h5py.File(root / name, "w") as handle:
            handle.create_dataset("000001.XSHE", data=np.asarray([1]))
    np.save(root / "trading_dates.npy", np.asarray([20150105, 20150106]))
    (root / "instruments.pk").write_bytes(b"fixture")
    (root / "share_transformation.json").write_text("{}", encoding="utf-8")
    assert all((root / name).exists() for name in REQUIRED_FILES)
    archive = tmp_path / "bundle.tar.bz2"
    with tarfile.open(archive, "w:bz2") as handle:
        handle.add(root, arcname="bundle")
    return archive


def test_safe_extract_and_schema_inspection(tmp_path: Path) -> None:
    archive = _bundle(tmp_path)
    digest = sha256(archive.read_bytes()).hexdigest()
    tree, report, inspection = extract_and_inspect(
        archive, tmp_path / "data", expected_sha256=digest
    )
    assert tree.is_dir()
    assert report.is_file()
    assert inspection.first_session == "2015-01-05"
    assert inspection.stock_symbols == 1
    assert inspection.status == "SCHEMA_READY_FOR_HISTORICAL_RESEARCH"


def test_safe_extract_rejects_path_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "unsafe.tar.bz2"
    with tarfile.open(archive, "w:bz2") as handle:
        member = tarfile.TarInfo("../escape")
        member.size = 1
        handle.addfile(member, io.BytesIO(b"x"))
    digest = sha256(archive.read_bytes()).hexdigest()
    with pytest.raises(BundleError, match="unsafe archive member"):
        extract_and_inspect(archive, tmp_path / "data", expected_sha256=digest)


def test_extract_rejects_wrong_hash(tmp_path: Path) -> None:
    archive = _bundle(tmp_path)
    with pytest.raises(BundleError, match="SHA-256"):
        extract_and_inspect(archive, tmp_path / "data", expected_sha256="0" * 64)
