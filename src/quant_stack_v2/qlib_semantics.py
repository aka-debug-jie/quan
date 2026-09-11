"""Capture source code that defines the pinned Qlib factor transformation."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import cast
from urllib.request import Request, urlopen

from quant_stack.snapshot import write_immutable

INVESTMENT_COMMIT = "b8c129b4d9b838f050eac8b1135111b3b79fc894"
QLIB_COMMIT = "b87a2c294d364a33fb739359886acffe8ec907d1"


@dataclass(frozen=True)
class SourceSpec:
    """One pinned source file and the semantics it must contain."""

    label: str
    url: str
    required_markers: tuple[str, ...]


SOURCES = (
    SourceSpec(
        "investment_normalize",
        f"https://raw.githubusercontent.com/chenditc/investment_data/{INVESTMENT_COMMIT}/qlib/normalize.py",
        ("CrowdSourceNormalize", "YahooNormalizeCN1d"),
    ),
    SourceSpec(
        "investment_dump",
        f"https://raw.githubusercontent.com/chenditc/investment_data/{INVESTMENT_COMMIT}/dump_qlib_bin.sh",
        (f'QLIB_COMMIT="{QLIB_COMMIT}"', "dump_bin.py"),
    ),
    SourceSpec(
        "qlib_collector",
        f"https://raw.githubusercontent.com/microsoft/qlib/{QLIB_COMMIT}/scripts/data_collector/yahoo/collector.py",
        ('df["factor"] = df["adjclose"] / df["close"]', 'df[_col] = df[_col] * df["factor"]'),
    ),
    SourceSpec(
        "qlib_dump",
        f"https://raw.githubusercontent.com/microsoft/qlib/{QLIB_COMMIT}/scripts/dump_bin.py",
        ("date_index", 'np.hstack([date_index, _df[field]]).astype("<f").tofile'),
    ),
)


@dataclass(frozen=True)
class FactorSemanticsReport:
    """Immutable evidence that binds factor formula and binary layout to one build."""

    schema_version: int
    archive_sha256: str
    investment_data_commit: str
    qlib_commit: str
    source_sha256: dict[str, str]
    status: str

    @property
    def identity_sha256(self) -> str:
        """Return the stable content identity."""
        return sha256(
            json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


Fetcher = Callable[[str], bytes]


def capture_factor_semantics(
    data_root: Path,
    *,
    archive_sha256: str,
    allow_network: bool,
    fetcher: Fetcher | None = None,
) -> tuple[Path, FactorSemanticsReport]:
    """Fetch pinned GitHub source files only with explicit network authority."""
    if not allow_network:
        raise ValueError("--allow-network is required for factor semantics capture")
    if len(archive_sha256) != 64:
        raise ValueError("factor semantics requires the Qlib archive SHA-256")
    captured: dict[str, str] = {}
    for source in SOURCES:
        content = (fetcher or _fetch)(source.url)
        text = content.decode("utf-8")
        if any(marker not in text for marker in source.required_markers):
            raise ValueError(f"pinned source no longer proves required semantics: {source.label}")
        digest = sha256(content).hexdigest()
        write_immutable(data_root / "qlib_factor_sources" / digest / f"{source.label}.py", content)
        captured[source.label] = digest
    report = FactorSemanticsReport(
        schema_version=1,
        archive_sha256=archive_sha256,
        investment_data_commit=INVESTMENT_COMMIT,
        qlib_commit=QLIB_COMMIT,
        source_sha256=captured,
        status="VERIFIED_FACTOR_SEMANTICS",
    )
    encoded = json.dumps(asdict(report), sort_keys=True, separators=(",", ":")).encode() + b"\n"
    path = data_root / "qlib_factor_semantics" / report.identity_sha256 / "report.json"
    write_immutable(path, encoded)
    receipt = {
        "schema_version": 1,
        "factor_semantics_sha256": report.identity_sha256,
        "retrieved_at_utc": datetime.now(UTC).isoformat(),
        "source_urls": {source.label: source.url for source in SOURCES},
    }
    receipt_bytes = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    write_immutable(
        data_root
        / "qlib_factor_semantics"
        / report.identity_sha256
        / "receipts"
        / f"{sha256(receipt_bytes).hexdigest()}.json",
        receipt_bytes,
    )
    return path, report


def _fetch(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "quant-stack-v2-semantics/1.0"})
    with urlopen(request, timeout=30) as response:
        return cast(bytes, response.read())
