"""Deterministic conservation tests for frozen free-evidence aggregation."""

import json
from hashlib import sha256
from pathlib import Path

from quant_stack_v2.free_evidence_funnel import aggregate, persist


def _write(root: Path, value: object) -> Path:
    body = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    path = root / (sha256(body).hexdigest() + ".json")
    path.write_bytes(body)
    return path


def test_funnel_conserves_and_replays(tmp_path: Path) -> None:
    audit = _write(
        tmp_path,
        {
            "issues": [
                {
                    "symbol": "sh600001",
                    "session": "2020-01-02",
                    "kind": "MISSING_OR_SUSPENDED_UNVERIFIED",
                },
                {
                    "symbol": "sz000001",
                    "session": "2020-01-03",
                    "kind": "MISSING_OR_SUSPENDED_UNVERIFIED",
                },
                {
                    "symbol": "sz000002",
                    "session": "2020-01-06",
                    "kind": "MISSING_OR_SUSPENDED_UNVERIFIED",
                },
            ]
        },
    )
    sse = _write(
        tmp_path, {"results": [{"task": {"symbol": "sh600001"}, "covered_dates": ["2020-01-02"]}]}
    )
    szse = _write(
        tmp_path,
        {
            "results": [
                {
                    "task": {"symbol": "sz000001"},
                    "dates": [{"session": "2020-01-03", "classification": "POST_DELISTING"}],
                },
                {
                    "task": {"symbol": "sz000002"},
                    "dates": [{"session": "2020-01-06", "classification": "UNEXPLAINED"}],
                },
            ]
        },
    )
    calendar = tmp_path / "day.txt"
    calendar.write_text("2020-01-02\n2020-01-03\n2020-01-06\n")
    first = aggregate(audit, sse, szse, calendar)
    second = aggregate(audit, sse, szse, calendar)
    assert first == second and sum(first["final_class_counts"].values()) == 3
    assert first["status"] == "FREE_EVIDENCE_RESIDUAL" and len(first["residual"]) == 1
    assert persist(first, tmp_path / "out") == persist(second, tmp_path / "out")
