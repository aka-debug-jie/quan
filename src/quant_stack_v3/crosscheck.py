"""Bounded BaoStock cross-check of the frozen RQAlpha raw-price sample."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from hashlib import sha256
from pathlib import Path

import pandas as pd

from quant_stack.research_json import canonical_json
from quant_stack.snapshot import write_immutable
from quant_stack_v2.baostock_provider import capture_baostock_requests


@dataclass(frozen=True)
class CrosscheckReport:
    """Aggregate independent-source agreement without redistributing source values."""

    schema_version: int
    sample_count: int
    captured_count: int
    failure_count: int
    matched_count: int
    mismatched_count: int
    price_tolerance: float
    relative_volume_amount_tolerance: float
    status: str
    sample_identity: str
    failure_reasons: tuple[str, ...]


def run_crosscheck(
    bars_path: Path,
    scores_path: Path,
    data_root: Path,
    artifact_root: Path,
    *,
    allow_network: bool,
    sample_count: int = 36,
) -> tuple[Path, CrosscheckReport]:
    """Capture and compare one fixed, evenly stratified set of symbol-date rows."""
    if not allow_network:
        raise ValueError("--allow-network is required for BaoStock cross-check")
    scores = pd.read_parquet(scores_path, columns=["session", "symbol", "score_rank"])
    scores = scores.sort_values(["session", "score_rank", "symbol"], kind="stable")
    if len(scores) < sample_count:
        raise ValueError("score cache is too small for the fixed cross-check")
    positions = [
        round(index * (len(scores) - 1) / (sample_count - 1)) for index in range(sample_count)
    ]
    samples = scores.iloc[positions].loc[:, ["session", "symbol"]].drop_duplicates()
    if len(samples) != sample_count:
        raise ValueError("fixed cross-check sampling produced duplicate keys")
    requests = tuple(
        sorted(
            (
                str(row.symbol),
                date.fromisoformat(str(row.session)[:10]),
                date.fromisoformat(str(row.session)[:10]),
            )
            for row in samples.itertuples()
        )
    )
    manifests, failures = capture_baostock_requests(
        data_root,
        requests=requests,
        allow_network=True,
        provider_version="0.8.9",
        workers=1,
    )
    filters = [
        [("session", "==", pd.Timestamp(session)), ("symbol", "==", symbol)]
        for symbol, session, _ in requests
    ]
    bars = pd.read_parquet(
        bars_path,
        columns=[
            "session",
            "symbol",
            "raw_open",
            "raw_high",
            "raw_low",
            "raw_close",
            "raw_volume",
            "amount",
            "st",
            "suspended",
        ],
        filters=filters,
    ).set_index(["session", "symbol"])
    mismatches: list[str] = []
    matched = 0
    for manifest in manifests:
        source = data_root / "baostock" / manifest.raw_sha256 / "response.csv"
        provider = pd.read_csv(source, dtype=str)
        key = (pd.Timestamp(manifest.start_date), manifest.symbol)
        if len(provider) != 1 or key not in bars.index:
            mismatches.append(f"{manifest.symbol}:{manifest.start_date}:missing_row")
            continue
        row = bars.loc[key]
        if not isinstance(row, pd.Series):
            raise ValueError("cross-check source key is not unique")
        candidate = provider.iloc[0]
        reasons = _compare(row, candidate)
        if reasons:
            mismatches.append(f"{manifest.symbol}:{manifest.start_date}:{','.join(reasons)}")
        else:
            matched += 1
    failure_reasons = tuple(
        sorted([f"{item.symbol}:{item.start_date}:{item.error}" for item in failures] + mismatches)
    )
    status = (
        "VENDOR_ARCHIVE_CROSSCHECKED_RESEARCH_ONLY"
        if matched >= 35 and not failures
        else "MATERIAL_CROSSCHECK_CONFLICT"
        if mismatches
        else "VENDOR_ARCHIVE_SINGLE_SOURCE_RESEARCH_ONLY"
    )
    sample_identity = sha256(
        canonical_json([{"symbol": symbol, "session": start} for symbol, start, _ in requests])
    ).hexdigest()
    report = CrosscheckReport(
        schema_version=1,
        sample_count=sample_count,
        captured_count=len(manifests),
        failure_count=len(failures),
        matched_count=matched,
        mismatched_count=len(mismatches),
        price_tolerance=0.01,
        relative_volume_amount_tolerance=0.001,
        status=status,
        sample_identity=sample_identity,
        failure_reasons=failure_reasons,
    )
    encoded = canonical_json(asdict(report)) + b"\n"
    path = artifact_root / "crosscheck" / f"{sha256(encoded).hexdigest()}.json"
    write_immutable(path, encoded)
    return path, report


def _compare(source: pd.Series, provider: pd.Series) -> list[str]:
    reasons: list[str] = []
    for local_name, provider_name in (
        ("raw_open", "open"),
        ("raw_high", "high"),
        ("raw_low", "low"),
        ("raw_close", "close"),
    ):
        if abs(float(source[local_name]) - float(provider[provider_name])) > 0.01:
            reasons.append(local_name)
    for local_name, provider_name in (("raw_volume", "volume"), ("amount", "amount")):
        local = float(source[local_name])
        remote = float(provider[provider_name])
        denominator = max(abs(local), abs(remote), 1.0)
        if abs(local - remote) / denominator > 0.001:
            reasons.append(local_name)
    if int(provider["tradestatus"]) != (0 if bool(source["suspended"]) else 1):
        reasons.append("tradestatus")
    if int(provider["isST"]) != int(bool(source["st"])):
        reasons.append("isST")
    return reasons
