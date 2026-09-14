"""Offline Qlib raw-reconstruction probe for the EXQ-001 residual scope."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import cast

from quant_stack_v2.af002 import _mapping
from quant_stack_v2.dev001 import ARCHIVE_SHA256, TREE_SHA256, _calendar, _qlib_root
from quant_stack_v2.dev_contract import canonical, write_blob
from quant_stack_v2.exq001 import qualify
from quant_stack_v2.qlib_qualification import _read_series

FIELDS = ("open", "high", "low", "close", "volume", "factor")


def probe(
    development_root: Path, sealed_root: Path, repo_root: Path, registry_path: Path
) -> dict[str, object]:
    """Check whether frozen residual keys have locally reconstructable Qlib raw bars."""
    qualification = qualify(development_root, sealed_root, repo_root, registry_path)
    rows = _mapping(
        _mapping(qualification, "lifecycle_and_suspension"), "free_residual_intersection"
    )
    if not isinstance(rows, list):
        raise ValueError("EXQ residual intersection is unavailable")
    qlib_root = _qlib_root(
        sealed_root / "artifacts/v2/qlib_import" / ARCHIVE_SHA256 / "trees" / TREE_SHA256
    )
    sessions = _calendar(qlib_root / "calendars/day.txt")
    status: Counter[str] = Counter()
    amount_files = 0
    cache: dict[str, dict[str, dict[date, float]]] = {}
    for row in rows:
        symbol, session = row["symbol"], row["expected_session"]
        if not isinstance(symbol, str) or not isinstance(session, str):
            raise ValueError("EXQ residual key is invalid")
        directory = qlib_root / "features" / symbol
        if (directory / "amount.day.bin").is_file():
            amount_files += 1
        values = cache.get(symbol)
        if values is None:
            if any(not (directory / f"{field}.day.bin").is_file() for field in FIELDS):
                status["MISSING_QLIB_FIELD"] += 1
                continue
            values = {
                field: _read_series(directory / f"{field}.day.bin", sessions) for field in FIELDS
            }
            cache[symbol] = values
        day = date.fromisoformat(session)
        bar = [values[field].get(day) for field in FIELDS]
        if any(value is None or not math.isfinite(value) for value in bar):
            status["MISSING_OR_NONFINITE"] += 1
            continue
        numbers = cast(list[float], bar)
        factor = numbers[-1]
        if factor <= 0 or any(value <= 0 for value in numbers[:4]):
            status["INVALID_RAW_RECONSTRUCTION"] += 1
            continue
        status["RECONSTRUCTABLE_QLIB_FACTOR"] += 1
    return {
        "schema_version": 1,
        "kind": "exq001_qlib_raw_reconstruction_probe",
        "status": "DIAGNOSTIC_ONLY_NOT_EXECUTION_QUALIFIED",
        "residual_keys_checked": len(rows),
        "status_counts": dict(sorted(status.items())),
        "amount_feature_files_for_residual_rows": amount_files,
        "formal_pit_status": "BLOCKED_DATA",
        "formal_research_status": "BLOCKED_DATA",
        "csi500": "NOT_STARTED",
        "provenance": {
            "archive_sha256": ARCHIVE_SHA256,
            "tree_sha256": TREE_SHA256,
            "registry_sha256": sha256(registry_path.read_bytes()).hexdigest(),
            "code_sha256": sha256(
                (repo_root / "src/quant_stack_v2/exq_qlib_probe.py").read_bytes()
            ).hexdigest(),
        },
    }


def main() -> None:
    """Write a content-addressed diagnostic receipt without exporting prices."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--development-root", type=Path, required=True)
    parser.add_argument("--sealed-root", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--result-root", type=Path, required=True)
    args = parser.parse_args()
    result = probe(args.development_root, args.sealed_root, args.repo_root, args.registry)
    identity = write_blob(args.result_root / "qlib_raw_probe", canonical(result))
    print(json.dumps({"receipt_sha256": identity, "status": result["status"]}, sort_keys=True))


if __name__ == "__main__":
    main()
