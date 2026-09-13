"""Diagnose sealed SZSE residuals without changing either qualification gate."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Any

from quant_stack_v2 import szse_monthly, szse_verification
from quant_stack_v2.szse_monthly import MonthlyEvent, load_months
from quant_stack_v2.szse_verification import match_day, persist_report


def evidence_hint(events: list[MonthlyEvent], session: date, months: set[str]) -> str:
    """Return a research lead, never a suspension classification or causal finding."""
    month = session.strftime("%Y-%m")
    if month not in months:
        return "OUTSIDE_ARCHIVED_MONTHS"
    if not events:
        return "NO_SYMBOL_RECORD"
    earlier = [e for e in events if e.start.date() <= session]
    if not earlier:
        return "NO_EARLIER_SUSPENSION_RECORD"
    latest = max(e.start for e in earlier)
    open_rows = [e for e in earlier if e.start == latest and e.resume is None and e.month < month]
    for event in open_rows:
        ended = any(
            other.resume is not None
            and event.start < other.resume
            and other.resume.date() <= session
            for other in events
        )
        if not ended:
            return "PRIOR_MONTH_OPEN_NEEDS_CONTINUATION_PROOF"
    return "OTHER_UNEXPLAINED"


def _event_ref(event: MonthlyEvent) -> dict[str, Any]:
    return {
        "start": event.start_text,
        "resume": event.resume.isoformat() if event.resume else None,
        "month": event.month,
        "raw_sha256": event.raw_sha256,
        "row_number": event.row_number,
        "official_url": event.official_url,
    }


def diagnose(report_path: Path, index: Path) -> dict[str, Any]:
    """Verify a prior report and group every residual date into bounded search tasks."""
    body = report_path.read_bytes()
    digest = sha256(body).hexdigest()
    if report_path.stem != digest:
        raise ValueError("sealed report SHA-256 mismatch")
    report = json.loads(body)
    if report["scope"] != "SZSE_MISSING_SESSIONS_ONLY_RETROSPECTIVE":
        raise ValueError("unexpected report scope")
    index_body = index.read_bytes()
    if report["index_sha256"] != sha256(index_body).hexdigest():
        raise ValueError("monthly index binding mismatch")
    for source in (Path(szse_monthly.__file__), Path(szse_verification.__file__)):
        if report["source_sha256"][source.name] != sha256(source.read_bytes()).hexdigest():
            raise ValueError("source version differs from original audit")
    events = load_months(index)
    months = {r["month"] for r in json.loads(index_body)["months"]}
    by_symbol: dict[str, list[MonthlyEvent]] = defaultdict(list)
    for event in events:
        by_symbol[event.symbol].append(event)
    expected = {(r["symbol"], r["session"]) for r in report["residual"]}
    if len(expected) != len(report["residual"]) or len(expected) != report["uncovered_sessions"]:
        raise ValueError("residual count mismatch")
    seen: set[tuple[str, str]] = set()
    leads: Counter[str] = Counter()
    years: Counter[str] = Counter()
    symbols: Counter[str] = Counter()
    tasks: list[dict[str, Any]] = []
    no_match: list[dict[str, Any]] = []
    for result in report["results"]:
        original = result["task"]
        symbol = original["symbol"]
        rows = by_symbol[symbol]
        if result["status"] == "NO_MATCH":
            no_match.append(original)
        active: dict[str, Any] | None = None
        for row in result["dates"]:
            if row["classification"] == "OFFICIAL_SUSPENDED":
                active = None
                continue
            key = (symbol, row["session"])
            if key in seen:
                raise ValueError("duplicate residual date")
            seen.add(key)
            session = date.fromisoformat(row["session"])
            reproduced = match_day(rows, session)
            if reproduced != row:
                raise ValueError("residual daily evidence differs from original audit")
            hint = (
                "EXISTING_CONFLICT"
                if row["classification"] == "CONFLICT"
                else evidence_hint(rows, session, months)
            )
            leads[hint] += 1
            years[str(session.year)] += 1
            symbols[symbol] += 1
            if active is not None and active["lead"] == hint:
                active["end_session"] = row["session"]
                active["session_count"] += 1
            else:
                earlier = sorted(
                    (e for e in rows if e.start.date() <= session),
                    key=lambda e: (e.start, e.month, e.row_number),
                )
                later = sorted(
                    (e for e in rows if e.start.date() > session),
                    key=lambda e: (e.start, e.month, e.row_number),
                )
                active = {
                    "symbol": symbol,
                    "start_session": row["session"],
                    "end_session": row["session"],
                    "session_count": 1,
                    "lead": hint,
                    "candidate_start": original["start_session"],
                    "candidate_end": original["end_session"],
                    "nearest_prior_event": _event_ref(earlier[-1]) if earlier else None,
                    "nearest_later_event": _event_ref(later[0]) if later else None,
                }
                tasks.append(active)
    if seen != expected:
        raise ValueError("results do not account for all residual dates")
    return {
        "schema_version": 1,
        "scope": "SZSE_RESIDUAL_SEARCH_LEADS_ONLY",
        "source_report_sha256": digest,
        "index_sha256": report["index_sha256"],
        "diagnostic_source_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "residual_sessions": len(seen),
        "residual_symbols": len(symbols),
        "lead_counts": dict(sorted(leads.items())),
        "year_counts": dict(sorted(years.items())),
        "symbol_counts": dict(sorted(symbols.items())),
        "task_count": len(tasks),
        "no_match_intervals": no_match,
        "top_tasks": sorted(
            tasks, key=lambda t: (-t["session_count"], t["symbol"], t["start_session"])
        )[:20],
        "tasks": tasks,
        "gap_gate": report["gap_gate"],
        "membership_gate": report["membership_gate"],
        "newly_explained_sessions": 0,
        "interpretation": (
            "SEARCH_LEADS_NOT_CAUSES; NO_OPEN_INTERVAL_EXTENSION; NO_RECLASSIFICATION"
        ),
    }


def main() -> None:
    """Persist full diagnostics in sealed storage and print a bounded research summary."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("report", "index", "output-root"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--expected-residuals", type=int, required=True)
    args = parser.parse_args()
    result = diagnose(args.report, args.index)
    if result["residual_sessions"] != args.expected_residuals:
        raise ValueError("unexpected residual session count")
    path = persist_report(result, args.output_root)
    summary = {k: v for k, v in result.items() if k not in ("tasks", "symbol_counts", "top_tasks")}
    summary["top_tasks"] = [
        {k: v for k, v in task.items() if not k.startswith("nearest_")}
        for task in result["top_tasks"]
    ]
    print(json.dumps(summary | {"report_path": str(path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
