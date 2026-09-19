"""Extraction must preserve evidence identity and the full planning context."""

import subprocess
from hashlib import sha256
from pathlib import Path

import pytest

from quant_stack_v2.exq_cninfo_extract import extract_pdf


def test_hash_mismatch_prevents_extraction(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "notice.pdf"
    path.write_bytes(b"changed")

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("unverified PDF reached extractor")

    monkeypatch.setattr(subprocess, "run", forbidden)
    with pytest.raises(ValueError, match="SHA-256"):
        extract_pdf(path, "0" * 64)


def test_long_planned_sentence_and_page_are_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "notice.pdf"
    path.write_bytes(b"%PDF-fixture")
    sentence = "预计" + "相关事项" * 100 + "公司股票复牌。"
    text = "第一页。\f" + sentence

    def extracted(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess([], 0, stdout=text.encode())

    monkeypatch.setattr(subprocess, "run", extracted)
    assert extract_pdf(path, sha256(path.read_bytes()).hexdigest()) == [
        {"page": 2, "anchor": sentence}
    ]
