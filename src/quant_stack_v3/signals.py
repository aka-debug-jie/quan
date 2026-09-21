"""Content-addressed construction of the frozen seven-factor score cache."""

from __future__ import annotations

import os
import tempfile
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path

import pandas as pd

from quant_stack.research_json import canonical_json
from quant_stack.snapshot import write_immutable
from quant_stack_v3.factors import build_scores
from quant_stack_v3.protocol import Protocol


@dataclass(frozen=True)
class SignalCacheReport:
    """Coverage and content identity of one frozen score table."""

    schema_version: int
    bars_sha256: str
    protocol_sha256: str
    scores_sha256: str
    cache_identity: str
    rows: int
    sessions: int
    first_session: str
    last_session: str
    minimum_cross_section: int
    maximum_cross_section: int
    status: str


def build_signal_cache(
    bars_path: Path,
    protocol_path: Path,
    protocol: Protocol,
    output_root: Path,
) -> tuple[Path, Path, SignalCacheReport]:
    """Calculate and publish factors once for every preregistered portfolio."""
    bars_digest = _file_sha256(bars_path)
    protocol_digest = sha256(protocol_path.read_bytes()).hexdigest()
    bars = pd.read_parquet(bars_path)
    scores = build_scores(bars, protocol)
    if scores.empty:
        raise ValueError("frozen historical input produced no score sessions")
    counts = scores.groupby("session").size()
    output_root.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".scores-", suffix=".parquet", dir=output_root
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        scores.to_parquet(temporary, index=False, compression="zstd")
        digest = _file_sha256(temporary)
        cache_identity = sha256(
            canonical_json(
                {
                    "bars_sha256": bars_digest,
                    "protocol_sha256": protocol_digest,
                    "scores_sha256": digest,
                }
            )
        ).hexdigest()
        destination = output_root / "signals" / cache_identity / "scores.parquet"
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if _file_sha256(destination) != digest:
                raise ValueError("existing score cache conflicts with its identity")
        else:
            temporary.replace(destination)
        report = SignalCacheReport(
            schema_version=1,
            bars_sha256=bars_digest,
            protocol_sha256=protocol_digest,
            scores_sha256=digest,
            cache_identity=cache_identity,
            rows=len(scores),
            sessions=int(scores.session.nunique()),
            first_session=str(scores.session.min().date()),
            last_session=str(scores.session.max().date()),
            minimum_cross_section=int(counts.min()),
            maximum_cross_section=int(counts.max()),
            status="FROZEN_SEVEN_FACTOR_SCORE_CACHE",
        )
        encoded = canonical_json(asdict(report)) + b"\n"
        report_path = output_root / "signals" / cache_identity / "report.json"
        write_immutable(report_path, encoded)
        return destination, report_path, report
    finally:
        temporary.unlink(missing_ok=True)


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
