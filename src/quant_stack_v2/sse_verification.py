"""Offline verification of archived SSE batches; never changes source evidence."""

from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from quant_stack.snapshot import write_immutable
from quant_stack_v2.sse_suspension import SSEManifest


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("expected JSON object")
    return value


def _digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _hash(value: str) -> str:
    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("invalid content identity")
    return value


def verify_response(raw: bytes, symbol: str) -> tuple[list[tuple[date, date]], list[str]]:
    """Require complete pagination and classify only full-day stock suspensions."""
    payload = json.loads(raw)
    rows = payload["result"]
    page = payload["pageHelp"]
    if not isinstance(rows, list) or page["total"] != len(rows):
        raise ValueError("pagination incomplete")
    if page["pageNo"] != 1 or page["pageCount"] not in (0, 1):
        raise ValueError("pagination incomplete")
    if "data" in page and page["data"] != rows:
        raise ValueError("pagination data conflict")
    if payload.get("sqlId") != "GW_PL_JYTS_TFPXX":
        raise ValueError("unexpected SSE query")
    accepted: list[tuple[date, date]] = []
    excluded: list[str] = []
    for row in rows:
        if row["productCode"] != symbol[2:]:
            raise ValueError("actual productCode mismatch")
        if row.get("controlType") != "TR":
            excluded.append("NON_STOCK_TRADING_BUSINESS")
            continue
        kind, timing = row.get("type"), row.get("stopTime")
        if kind not in ("LXTP", "LSTP"):
            excluded.append("UNKNOWN_SUSPENSION_TYPE")
            continue
        if timing in ("AM", "PM", "930"):
            excluded.append("INTRADAY_ONLY")
            continue
        if not (timing == "WH" or (kind == "LXTP" and timing == "")):
            excluded.append("UNVERIFIED_FULL_DAY_SEMANTICS")
            continue
        start = datetime.strptime(row["startStopDate"], "%Y%m%d").date()
        end = datetime.strptime(row["endStopDate"], "%Y%m%d").date()
        if end < start:
            raise ValueError("reversed official dates")
        accepted.append((start, end))
    return accepted, excluded


def verify_batch(index: Path, plan: Path, audit: Path, data_root: Path) -> dict[str, Any]:
    """Verify every task and match official intervals against actual missing dates."""
    batch, tasks_payload, daily = _load(index), _load(plan), _load(audit)
    if index.parent.name != _digest(index) or plan.stem != _digest(plan):
        raise ValueError("batch or plan content hash mismatch")
    if batch["plan_sha256"] != _digest(plan):
        raise ValueError("batch plan binding mismatch")
    if tasks_payload["audit_sha256"] != _digest(audit):
        raise ValueError("plan audit binding mismatch")
    tasks = [r for r in tasks_payload["intervals"] if r["exchange"] == "SH"]
    ids = batch["manifest_sha256s"]
    if batch["exchange"] != "SSE" or batch["task_count"] != len(tasks) or len(ids) != len(tasks):
        raise ValueError("batch task count mismatch")
    missing = {
        (r["symbol"], date.fromisoformat(r["session"]))
        for r in daily["issues"]
        if r["kind"] == "MISSING_OR_SUSPENDED_UNVERIFIED" and r["symbol"].startswith("sh")
    }
    claimed: set[tuple[str, date]] = set()
    results: list[dict[str, Any]] = []
    for task, identity in zip(tasks, ids, strict=True):
        symbol = task["symbol"]
        start, end = (
            date.fromisoformat(task["start_session"]),
            date.fromisoformat(task["end_session"]),
        )
        dates = sorted(d for s, d in missing if s == symbol and start <= d <= end)
        selected = {(symbol, d) for d in dates}
        if len(dates) != task["session_count"] or claimed & selected:
            raise ValueError("candidate plan overlaps or differs from audit dates")
        claimed.update(selected)
        result: dict[str, Any] = {"task": task, "manifest_id": identity}
        try:
            manifest_path = (
                data_root / "sse_suspension_manifests" / _hash(identity) / "manifest.json"
            )
            manifest = SSEManifest(**_load(manifest_path))
            if manifest.identity_sha256 != identity:
                raise ValueError("manifest hash mismatch")
            if (manifest.symbol, manifest.start_date, manifest.end_date) != (
                symbol,
                task["start_session"],
                task["end_session"],
            ):
                raise ValueError("manifest request differs from plan")
            raw_path = data_root / "sse_suspension" / _hash(manifest.raw_sha256) / "response.json"
            raw = raw_path.read_bytes()
            if sha256(raw).hexdigest() != manifest.raw_sha256:
                raise ValueError("raw SHA-256 mismatch")
            if manifest.event_count != len(json.loads(raw)["result"]):
                raise ValueError("event count mismatch")
            spans, excluded = verify_response(raw, symbol)
            covered = [d for d in dates if any(a <= d <= b for a, b in spans)]
            result.update(
                manifest_file_sha256=_digest(manifest_path),
                raw_sha256=manifest.raw_sha256,
                excluded=excluded,
                covered_dates=[d.isoformat() for d in covered],
                uncovered_dates=[d.isoformat() for d in dates if d not in covered],
                status="FULL"
                if len(covered) == len(dates)
                else "PARTIAL"
                if covered
                else "NO_MATCH",
            )
        except (OSError, ValueError, KeyError, TypeError) as error:
            result.update(
                status="CONFLICT",
                reason=str(error),
                covered_dates=[],
                uncovered_dates=[d.isoformat() for d in dates],
            )
        results.append(result)
    if claimed != missing:
        raise ValueError("plan does not account for all SSE missing sessions")
    counts = {
        s: sum(r["status"] == s for r in results)
        for s in ("FULL", "PARTIAL", "NO_MATCH", "CONFLICT")
    }
    return {
        "schema_version": 1,
        "verifier_source_sha256": _digest(Path(__file__)),
        "batch_sha256": _digest(index),
        "audit_sha256": _digest(audit),
        "plan_sha256": _digest(plan),
        "interval_counts": counts,
        "missing_sessions": len(missing),
        "covered_sessions": sum(len(r["covered_dates"]) for r in results),
        "uncovered_sessions": sum(len(r["uncovered_dates"]) for r in results),
        "status": "PASS" if counts["FULL"] == len(results) and results else "BLOCKED_DATA",
        "scope": "SSE_MISSING_SESSIONS_ONLY",
        "results": results,
    }


def main() -> None:
    """Run offline verification from an installed wheel with absolute input paths."""
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("index", "plan", "audit", "data-root", "output-root"):
        parser.add_argument("--" + option, type=Path, required=True)
    args = parser.parse_args()
    result = verify_batch(args.index, args.plan, args.audit, args.data_root)
    body = json.dumps(result, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    output = args.output_root / (sha256(body).hexdigest() + ".json")
    write_immutable(output, body)
    print(
        json.dumps(
            {k: v for k, v in result.items() if k != "results"} | {"report_path": str(output)}
        )
    )
    raise SystemExit(0 if result["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
