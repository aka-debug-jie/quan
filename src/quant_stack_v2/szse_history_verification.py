"""Final offline replay of actual-resumption and bounded-history issuer evidence."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from hashlib import sha256
from pathlib import Path
from typing import Any

from quant_stack_v2.szse_history import MONTHLY_INDEX, apply_histories, load_histories
from quant_stack_v2.szse_issuer_supplement import supplement
from quant_stack_v2.szse_lifecycle import apply_delistings, load_delistings
from quant_stack_v2.szse_verification import persist_report

COVERED = {
    "OFFICIAL_SUSPENDED",
    "ISSUER_CONFIRMED_SUSPENDED",
    "ISSUER_CONFIRMED_HISTORY",
    "POST_DELISTING",
}


def verify(
    report: Path, issuer: Path, history: Path, lifecycle: Path | None = None
) -> dict[str, Any]:
    """Recompute all intervals while preserving monthly, actual and history provenance."""
    result = supplement(report, issuer)
    histories = load_histories(history)
    rows = [
        [r["task"]["symbol"], d["session"], d["classification"]]
        for r in result["results"]
        for d in r["dates"]
    ]
    _, changes = apply_histories(rows, histories, result["claims"])
    terminal_claims = load_delistings(lifecycle) if lifecycle else []
    post = {
        (s, d)
        for s, d, label in apply_delistings(rows, terminal_claims)
        if label == "POST_DELISTING"
    }
    mapping = {(c["symbol"], c["session"]): c for c in changes}
    residual = []
    tasks = []
    for item in result["results"]:
        symbol = item["task"]["symbol"]
        for row in item["dates"]:
            change = mapping.get((symbol, row["session"]))
            if change:
                row.update(
                    classification="ISSUER_CONFIRMED_HISTORY",
                    reason="DATED_SUSPENSION_HISTORY",
                    evidence=change["evidence"],
                )
            if (symbol, row["session"]) in post:
                row.update(
                    classification="POST_DELISTING",
                    reason="ISSUER_REPORTED_DELISTING_EFFECTIVE",
                    evidence=[c for c in terminal_claims if c["symbol"] == symbol],
                )
            if row["classification"] not in COVERED:
                residual.append({"symbol": symbol, **row})
        counts = Counter(d["classification"] for d in item["dates"])
        covered = sum(counts[k] for k in COVERED)
        item["daily_counts"] = dict(counts)
        item["status"] = (
            "CONFLICT"
            if counts["CONFLICT"]
            else "FULL"
            if covered == len(item["dates"])
            else "PARTIAL"
            if covered
            else "NO_MATCH"
        )
        remaining = [d["session"] for d in item["dates"] if d["classification"] not in COVERED]
        if remaining:
            tasks.append(
                {
                    "symbol": symbol,
                    "candidate_start": item["task"]["start_session"],
                    "candidate_end": item["task"]["end_session"],
                    "remaining_first": min(remaining),
                    "remaining_last": max(remaining),
                    "remaining_session_count": len(remaining),
                }
            )
    actual_by_symbol = Counter(
        r["task"]["symbol"]
        for r in result["results"]
        for d in r["dates"]
        if d["classification"] == "ISSUER_CONFIRMED_SUSPENDED"
    )
    actual_added = sum(actual_by_symbol.values())
    changes = [c for c in changes if (c["symbol"], c["session"]) not in post]
    history_by_symbol = Counter(c["symbol"] for c in changes)
    combined = actual_by_symbol + history_by_symbol
    result.update(
        scope="SZSE_MONTHLY_PLUS_ACTUAL_AND_DATED_HISTORY_RETROSPECTIVE",
        actual_notice_explained_sessions=actual_added,
        history_explained_sessions=len(changes),
        history_explained_by_symbol=dict(sorted(history_by_symbol.items())),
        newly_explained_sessions=actual_added + len(changes),
        newly_explained_by_symbol=dict(sorted(combined.items())),
        covered_sessions=result["source_missing_sessions"] - len(residual),
        uncovered_sessions=len(residual),
        residual=residual,
        interval_counts={
            s: sum(r["status"] == s for r in result["results"])
            for s in ("FULL", "PARTIAL", "NO_MATCH", "CONFLICT")
        },
        gap_gate="BLOCKED_DATA" if residual else "PASS",
        history_manifest_sha256=history.stem,
        history_source_sha256=sha256(
            Path(__file__).with_name("szse_history.py").read_bytes()
        ).hexdigest(),
        replay_source_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        history_monthly_index_sha256=MONTHLY_INDEX.stem,
        post_delisting_sessions=len(post),
        lifecycle_manifest_sha256=lifecycle.stem if lifecycle else None,
        lifecycle_source_sha256=sha256(
            Path(__file__).with_name("szse_lifecycle.py").read_bytes()
        ).hexdigest()
        if lifecycle
        else None,
        lifecycle_claims=terminal_claims,
        history_claims=histories,
        residual_evidence_tasks=sorted(
            tasks,
            key=lambda t: (
                -int(t["remaining_session_count"]),
                str(t["symbol"]),
                str(t["candidate_start"]),
            ),
        ),
    )
    result["top_residual_tasks"] = result["residual_evidence_tasks"][:20]
    return result


def main() -> None:
    """Persist the immutable full replay; publish reduced counts and all search envelopes."""
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("report", "issuer", "history", "output-root"):
        parser.add_argument("--" + key, required=True, type=Path)
    parser.add_argument("--lifecycle", type=Path)
    args = parser.parse_args()
    result = verify(args.report, args.issuer, args.history, args.lifecycle)
    path = persist_report(result, args.output_root)
    hidden = {
        "results",
        "residual",
        "claims",
        "history_claims",
        "lifecycle_claims",
        "notice_conflicts",
    }
    print(
        json.dumps(
            {k: v for k, v in result.items() if k not in hidden} | {"report_path": str(path)}
        )
    )
    raise SystemExit(0 if result["gap_gate"] == result["membership_gate"] == "PASS" else 1)


if __name__ == "__main__":
    main()
