"""Offline, deterministic aggregation of frozen V2 free-evidence reports."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Any

from quant_stack.snapshot import write_immutable

CLASSES = (
    "PRE_LISTING",
    "POST_DELISTING",
    "MARKET_CLOSED",
    "OFFICIAL_SUSPENDED",
    "INDEPENDENT_PROVIDER_CONFIRMED",
    "PROVIDER_CONFLICT",
    "UNEXPLAINED",
)


def _load(path: Path) -> tuple[dict[str, Any], str]:
    body = path.read_bytes()
    value = json.loads(body)
    if not isinstance(value, dict):
        raise ValueError("frozen input must be an object")
    return value, sha256(body).hexdigest()


def aggregate(audit: Path, sse: Path, szse: Path, sessions: Path) -> dict[str, Any]:
    """Classify every Qlib expected-session missing key exactly once from frozen reports."""
    qlib, audit_sha = _load(audit)
    sse_report, sse_sha = _load(sse)
    szse_report, szse_sha = _load(szse)
    calendar = tuple(
        date.fromisoformat(line.strip())
        for line in sessions.read_text().splitlines()
        if line.strip()
    )
    calendar_set = set(calendar)
    missing = [
        (str(r["symbol"]), date.fromisoformat(r["session"]))
        for r in qlib["issues"]
        if r["kind"] == "MISSING_OR_SUSPENDED_UNVERIFIED"
    ]
    if len(missing) != len(set(missing)):
        raise ValueError("duplicate missing session")
    evidence: dict[tuple[str, date], tuple[str, str | None]] = {}
    for item in sse_report.get("results", []):
        symbol = item["task"]["symbol"]
        for day in item.get("post_delisting", []):
            evidence[(symbol, date.fromisoformat(day))] = ("POST_DELISTING", sse.stem)
        for day in item.get("covered_dates", item.get("official_suspended", [])):
            evidence[(symbol, date.fromisoformat(day))] = ("OFFICIAL_SUSPENDED", sse.stem)
    for item in szse_report.get("results", []):
        symbol = item["task"]["symbol"]
        for row in item.get("dates", []):
            label = row["classification"]
            key = (symbol, date.fromisoformat(row["session"]))
            if label == "POST_DELISTING":
                evidence[key] = ("POST_DELISTING", szse.stem)
            elif label in {
                "OFFICIAL_SUSPENDED",
                "ISSUER_CONFIRMED_SUSPENDED",
                "ISSUER_CONFIRMED_HISTORY",
            }:
                evidence[key] = ("OFFICIAL_SUSPENDED", szse.stem)
            elif label == "CONFLICT":
                evidence[key] = ("PROVIDER_CONFLICT", szse.stem)
    rows: list[dict[str, Any]] = []
    for symbol, day in sorted(missing):
        final_label: str
        source: str | None
        if day not in calendar_set:
            final_label, source = "MARKET_CLOSED", "calendar"
        else:
            final_label, source = evidence.get((symbol, day), ("UNEXPLAINED", None))
        rows.append(
            {
                "symbol": symbol,
                "session": day.isoformat(),
                "classification": final_label,
                "evidence_sha256": source,
            }
        )
    counts = Counter(r["classification"] for r in rows)
    if (
        set(counts) - set(CLASSES)
        or len(rows) != len(missing)
        or sum(counts.values()) != len(missing)
    ):
        raise ValueError("funnel conservation failure")
    intervals: list[dict[str, Any]] = []
    pos = {d: i for i, d in enumerate(calendar)}
    for row in rows:
        if row["classification"] not in {"OFFICIAL_SUSPENDED", "INDEPENDENT_PROVIDER_CONFIRMED"}:
            continue
        day = date.fromisoformat(str(row["session"]))
        if (
            intervals
            and intervals[-1]["symbol"] == row["symbol"]
            and intervals[-1]["classification"] == row["classification"]
            and pos[day] == pos[date.fromisoformat(str(intervals[-1]["end_session"]))] + 1
        ):
            intervals[-1]["end_session"] = row["session"]
            intervals[-1]["session_count"] = int(intervals[-1]["session_count"]) + 1
        else:
            intervals.append(
                {
                    "symbol": row["symbol"],
                    "exchange": row["symbol"][:2].upper(),
                    "classification": row["classification"],
                    "start_session": row["session"],
                    "end_session": row["session"],
                    "session_count": 1,
                    "evidence_sha256": row["evidence_sha256"],
                }
            )
    residual = [r for r in rows if r["classification"] in {"PROVIDER_CONFLICT", "UNEXPLAINED"}]
    status = "FREE_EVIDENCE_COMPLETE" if not residual else "FREE_EVIDENCE_RESIDUAL"
    return {
        "schema_version": 1,
        "scope": "FREE_EVIDENCE_FUNNEL_FROZEN_ARCHIVES_ONLY",
        "inputs": {
            "audit_file_sha256": audit_sha,
            "audit_identity": audit.stem,
            "sse_file_sha256": sse_sha,
            "sse_identity": sse.stem,
            "szse_file_sha256": szse_sha,
            "szse_identity": szse.stem,
            "calendar_sha256": sha256(sessions.read_bytes()).hexdigest(),
        },
        "initial_missing": len(missing),
        "final_class_counts": {k: counts[k] for k in CLASSES},
        "sessions": rows,
        "intervals": intervals,
        "residual": residual,
        "unique_suspension_intervals": len(intervals),
        "gap_gate": "PASS" if not residual else "INCOMPLETE",
        "status": status,
        "FORMAL_PIT_STATUS": "BLOCKED_DATA",
        "FORMAL_RESEARCH_STATUS": "BLOCKED_DATA",
    }


def persist(result: dict[str, Any], root: Path) -> dict[str, str]:
    """Write independent content-addressed sessions, intervals, residual and summary artifacts."""
    outputs = {}
    for name in ("sessions", "intervals", "residual"):
        body = (
            json.dumps(
                {"schema_version": 1, name: result[name]}, sort_keys=True, separators=(",", ":")
            ).encode()
            + b"\n"
        )
        digest = sha256(body).hexdigest()
        write_immutable(root / name / (digest + ".json"), body)
        outputs[name] = digest
    summary = {
        k: v for k, v in result.items() if k not in {"sessions", "intervals", "residual"}
    } | {"artifacts": outputs}
    body = json.dumps(summary, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    digest = sha256(body).hexdigest()
    write_immutable(root / "funnel" / (digest + ".json"), body)
    outputs["funnel"] = digest
    return outputs


def main() -> None:
    """Replay frozen inputs twice and refuse nondeterministic outputs."""
    parser = argparse.ArgumentParser()
    for name in ("audit", "sse", "szse", "calendar", "output-root"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    first = aggregate(args.audit, args.sse, args.szse, args.calendar)
    first_hashes = persist(first, args.output_root)
    second = aggregate(args.audit, args.sse, args.szse, args.calendar)
    second_hashes = persist(second, args.output_root)
    if first_hashes != second_hashes:
        raise ValueError("frozen replay is not deterministic")
    print(
        json.dumps(
            {k: v for k, v in first.items() if k not in {"sessions", "intervals", "residual"}}
            | {"reproducibility_hashes": first_hashes},
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
