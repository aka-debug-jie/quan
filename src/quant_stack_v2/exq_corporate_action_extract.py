# ruff: noqa: RUF001
"""Extract page-bound corporate-action candidate fields without creating ledger events."""

from __future__ import annotations

import re
from hashlib import sha256
from pathlib import Path

DATE_FIELD = re.compile(
    r"(股权登记日|除权除息日|换股股权登记日|终止上市日)[：:为]*([0-9]{4}年[0-9]{1,2}月[0-9]{1,2}日)"
)
TERM = re.compile(r"每\s*10\s*股|现金选择权|换股|终止上市|权益分派")


def extract(text: str) -> list[dict[str, object]]:
    """Return complete page-bound sentences that contain candidate accounting terms."""
    rows: list[dict[str, object]] = []
    for page, content in enumerate(text.split("\f"), 1):
        for sentence in re.findall(r"[^。！？]+[。！？]|[^。！？]+$", content.replace(chr(10), "")):
            if TERM.search(sentence):
                fields = {key: value for key, value in DATE_FIELD.findall(sentence)}
                rows.append({"page": page, "anchor": sentence.strip(), "date_fields": fields})
    return rows


def verify_pdf(path: Path, digest: str) -> None:
    """Reject a PDF body unless it still equals its content-addressed identity."""
    if not path.is_file() or path.is_symlink() or sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError("corporate-action PDF identity mismatch")
