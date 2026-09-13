"""Offline daily matching of SZSE monthly evidence to the sealed Qlib audit."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Any

from quant_stack.snapshot import write_immutable
from quant_stack_v2 import szse_monthly
from quant_stack_v2.szse_monthly import MonthlyEvent, load_months


def _digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def match_day(events: list[MonthlyEvent], session: date) -> dict[str, Any]:
    """Match a whole missing session, retaining conflicts and row-level provenance."""
    groups: dict[str, list[MonthlyEvent]] = defaultdict(list)
    for event in events:
        groups[event.start_text].append(event)
    supporting: list[MonthlyEvent] = []
    conflicts: list[MonthlyEvent] = []
    boundary: list[MonthlyEvent] = []
    for group in groups.values():
        resumes = {e.resume for e in group if e.resume is not None}
        resume = min(resumes) if resumes else None
        for event in group:
            limit = resume
            if event.resume is None:
                # A later event or any actual resumption ends this open claim.
                boundaries = [
                    point
                    for other in events
                    for point in (other.start, other.resume)
                    if point is not None and point > event.start
                ]
                if limit is not None:
                    boundaries.append(limit)
                limit = min(boundaries) if boundaries else None
            first, last = event.full_days(limit)
            if first <= session <= last:
                supporting.append(event)
            # Disagreeing actual resume times are not resolved by choosing one source.
            if len(resumes) > 1 and event.start.date() <= session <= max(resumes).date():
                conflicts.append(event)
            if (event.start_is_intraday and session == event.start.date()) or (
                event.resume is not None and session == event.resume.date()
            ):
                boundary.append(event)
    status = (
        "CONFLICT"
        if conflicts or boundary
        else "OFFICIAL_SUSPENDED"
        if supporting
        else "UNEXPLAINED"
    )
    evidence = sorted(set(supporting + conflicts + boundary), key=lambda e: (e.month, e.row_number))
    return {
        "session": session.isoformat(),
        "classification": status,
        "reason": "ACTUAL_RESUME_DISAGREEMENT"
        if conflicts
        else "TRADING_BOUNDARY"
        if boundary
        else "FULL_SESSION_EVIDENCE"
        if supporting
        else "NO_FULL_SESSION_EVIDENCE",
        "evidence": [
            {
                "month": e.month,
                "row_number": e.row_number,
                "raw_sha256": e.raw_sha256,
                "official_url": e.official_url,
                "start": e.start_text,
                "resume": e.resume.isoformat() if e.resume else None,
                "kind": e.kind,
            }
            for e in evidence
        ],
    }


def verify_monthly(index: Path, plan: Path, audit: Path) -> dict[str, Any]:
    """Bind the plan to the full daily audit and account for every SZ missing date."""
    events = load_months(index)
    plan_body, audit_body = plan.read_bytes(), audit.read_bytes()
    tasks_payload, daily = json.loads(plan_body), json.loads(audit_body)
    if plan.stem != sha256(plan_body).hexdigest():
        raise ValueError("plan SHA-256 mismatch")
    if tasks_payload["audit_sha256"] != sha256(audit_body).hexdigest():
        raise ValueError("plan audit binding mismatch")
    missing_rows = [
        (r["symbol"], date.fromisoformat(r["session"]))
        for r in daily["issues"]
        if r["kind"] == "MISSING_OR_SUSPENDED_UNVERIFIED" and r["symbol"].startswith("sz")
    ]
    missing = set(missing_rows)
    if len(missing) != len(missing_rows):
        raise ValueError("duplicate missing session")
    by_symbol: dict[str, list[MonthlyEvent]] = defaultdict(list)
    for event in events:
        by_symbol[event.symbol].append(event)
    claimed: set[tuple[str, date]] = set()
    results: list[dict[str, Any]] = []
    residual: list[dict[str, Any]] = []
    daily_counts: Counter[str] = Counter()
    for task in tasks_payload["intervals"]:
        if task["exchange"] != "SZ":
            continue
        symbol = task["symbol"]
        start, end = (
            date.fromisoformat(task["start_session"]),
            date.fromisoformat(task["end_session"]),
        )
        selected = {(s, d) for s, d in missing if s == symbol and start <= d <= end}
        dates = sorted(d for _, d in selected)
        if not dates or len(dates) != task["session_count"] or claimed & selected:
            raise ValueError("candidate plan overlaps or differs from audit dates")
        if dates[0] != start or dates[-1] != end:
            raise ValueError("candidate boundaries differ from audit dates")
        claimed.update(selected)
        rows = [match_day(by_symbol[symbol], d) for d in dates]
        counts = Counter(r["classification"] for r in rows)
        daily_counts.update(counts)
        status = (
            "CONFLICT"
            if counts["CONFLICT"]
            else "FULL"
            if counts["OFFICIAL_SUSPENDED"] == len(rows)
            else "PARTIAL"
            if counts["OFFICIAL_SUSPENDED"]
            else "NO_MATCH"
        )
        results.append(
            {"task": task, "status": status, "daily_counts": dict(counts), "dates": rows}
        )
        residual.extend(
            {"symbol": symbol, **row}
            for row in rows
            if row["classification"] != "OFFICIAL_SUSPENDED"
        )
    if claimed != missing or not results:
        raise ValueError("plan does not account for all SZSE missing sessions")
    interval_counts = {
        s: sum(r["status"] == s for r in results)
        for s in ("FULL", "PARTIAL", "NO_MATCH", "CONFLICT")
    }
    return {
        "schema_version": 1,
        "scope": "SZSE_MISSING_SESSIONS_ONLY_RETROSPECTIVE",
        "index_sha256": _digest(index),
        "plan_sha256": _digest(plan),
        "audit_sha256": _digest(audit),
        "source_sha256": {
            "szse_verification.py": _digest(Path(__file__)),
            "szse_monthly.py": _digest(Path(szse_monthly.__file__)),
        },
        "monthly_tables": len(json.loads(index.read_bytes())["months"]),
        "parsed_events": len(events),
        "event_counts": dict(Counter(e.kind for e in events)),
        "interval_counts": interval_counts,
        "missing_sessions": len(missing),
        "covered_sessions": daily_counts["OFFICIAL_SUSPENDED"],
        "unexplained_sessions": daily_counts["UNEXPLAINED"],
        "conflict_sessions": daily_counts["CONFLICT"],
        "uncovered_sessions": len(residual),
        "gap_gate": "PASS" if not residual else "BLOCKED_DATA",
        "membership_gate": "BLOCKED_DATA",
        "membership_reason": (
            "CSI_OFFICIAL_PIT_ADJUSTMENT_DATES_UNVERIFIED; "
            "SUSPENSION_EVIDENCE_DOES_NOT_QUALIFY_MEMBERSHIP"
        ),
        "results": results,
        "residual": residual,
    }


def persist_report(result: dict[str, Any], root: Path) -> Path:
    """Write a deterministic, content-addressed report without replacing evidence."""
    body = (
        json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        + b"\n"
    )
    path = root / (sha256(body).hexdigest() + ".json")
    write_immutable(path, body)
    return path


def main() -> None:
    """Parse public evidence alone or match it against a plan and sealed audit."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", required=True, type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--audit", type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--expected-intervals", type=int)
    parser.add_argument("--expected-sessions", type=int)
    args = parser.parse_args()
    if (args.plan is None) != (args.audit is None):
        parser.error("--plan and --audit must be supplied together")
    result: dict[str, Any]
    if args.plan is None:
        events = load_months(args.index)
        result = {
            "scope": "PUBLIC_MONTHLY_PARSE_ONLY",
            "index_sha256": _digest(args.index),
            "parser_source_sha256": _digest(Path(szse_monthly.__file__)),
            "monthly_tables": len(json.loads(args.index.read_bytes())["months"]),
            "event_counts": dict(Counter(e.kind for e in events)),
            "intraday_start_events": sum(e.start_is_intraday for e in events),
            "gap_gate": "NOT_RUN",
            "membership_gate": "BLOCKED_DATA",
            "events": [
                {
                    **asdict(e),
                    "start": e.start.isoformat(),
                    "resume": e.resume.isoformat() if e.resume else None,
                }
                for e in events
            ],
        }
    else:
        result = verify_monthly(args.index, args.plan, args.audit)
    if args.plan is not None:
        if (
            args.expected_intervals is not None
            and len(result["results"]) != args.expected_intervals
        ):
            raise ValueError("unexpected candidate interval count")
        if (
            args.expected_sessions is not None
            and result["missing_sessions"] != args.expected_sessions
        ):
            raise ValueError("unexpected missing session count")
    path = persist_report(result, args.output_root)
    print(
        json.dumps(
            {k: v for k, v in result.items() if k not in ("events", "results", "residual")}
            | {"report_path": str(path)}
        )
    )
    raise SystemExit(1 if result["gap_gate"] == "BLOCKED_DATA" else 0)


if __name__ == "__main__":
    main()
