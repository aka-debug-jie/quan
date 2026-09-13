"""Export a bounded, complete evidence-request queue from a sealed SZSE report."""

from __future__ import annotations

import argparse
import json
from hashlib import sha256
from pathlib import Path
from typing import Any

from quant_stack_v2.szse_verification import persist_report


def build_queue(path: Path) -> dict[str, Any]:
    """Verify the report and account for all residual dates without exporting raw prices."""
    body = path.read_bytes()
    digest = sha256(body).hexdigest()
    if path.stem != digest:
        raise ValueError("report SHA-256 mismatch")
    report = json.loads(body)
    if report["scope"] != "SZSE_MONTHLY_PLUS_ISSUER_NOTICES_RETROSPECTIVE":
        raise ValueError("unexpected report scope")
    residual = {(r["symbol"], r["session"]) for r in report["residual"]}
    if len(residual) != len(report["residual"]) or len(residual) != report["uncovered_sessions"]:
        raise ValueError("residual count mismatch")
    seen: set[tuple[str, str]] = set()
    rows: list[list[str | int]] = []
    for item in report["results"]:
        task = item["task"]
        dates = [
            r["session"]
            for r in item["dates"]
            if r["classification"] not in ("OFFICIAL_SUSPENDED", "ISSUER_CONFIRMED_SUSPENDED")
        ]
        keys = {(task["symbol"], d) for d in dates}
        if len(keys) != len(dates) or seen & keys:
            raise ValueError("duplicate residual in results")
        seen.update(keys)
        if dates:
            rows.append(
                [
                    task["symbol"],
                    task["start_session"],
                    task["end_session"],
                    min(dates),
                    max(dates),
                    len(dates),
                ]
            )
    if seen != residual:
        raise ValueError("results and residual differ")
    rows.sort(key=lambda r: (-int(r[5]), str(r[0]), str(r[1])))
    return {
        "scope": "ALL_SZSE_RESIDUAL_EVIDENCE_REQUESTS_NO_RAW_PRICES",
        "source_report_sha256": digest,
        "queue_source_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "residual_sessions": len(residual),
        "task_count": len(rows),
        "columns": [
            "symbol",
            "candidate_start",
            "candidate_end",
            "remaining_first",
            "remaining_last",
            "remaining_session_count",
        ],
        "rows": rows,
        "gap_gate": report["gap_gate"],
        "membership_gate": report["membership_gate"],
        "interpretation": "DATE_ENVELOPES_ARE_SEARCH_RANGES_NOT_CONTINUOUS_SUSPENSION_PROOF",
    }


def main() -> None:
    """Print all evidence requests and archive the same reduced queue in sealed storage."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("report", "output-root"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--expected-residuals", type=int, required=True)
    args = parser.parse_args()
    result = build_queue(args.report)
    if result["residual_sessions"] != args.expected_residuals:
        raise ValueError("unexpected residual count")
    path = persist_report(result, args.output_root)
    print(json.dumps(result | {"report_path": str(path)}, separators=(",", ":")))


if __name__ == "__main__":
    main()
