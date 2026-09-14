"""Capture official SSE suspension records for the exact EXQ queue."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from quant_stack_v2.dev_contract import canonical, read_blob, write_blob
from quant_stack_v2.sse_suspension import capture_sse_suspensions


def main() -> None:
    """Archive the SSE subset of one hash-pinned EXQ official queue."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue-root", type=Path, required=True)
    parser.add_argument("--queue-sha256", required=True)
    parser.add_argument("--sealed-root", type=Path, required=True)
    parser.add_argument("--result-root", type=Path, required=True)
    parser.add_argument("--allow-network", action="store_true")
    args = parser.parse_args()
    queue = json.loads(read_blob(args.queue_root, args.queue_sha256))
    tasks = [task for task in queue["tasks"] if task["exchange"] == "SSE"]
    results = []
    for task in tasks:
        sessions = tuple(date.fromisoformat(item) for item in task["exact_sessions"])
        path, manifest, events = capture_sse_suspensions(
            args.sealed_root / "artifacts/v2/exq001_candidate_scope/sse",
            symbol=task["symbol"],
            start=min(sessions),
            end=max(sessions),
            allow_network=args.allow_network,
        )
        results.append(
            {
                "symbol": task["symbol"],
                "sessions": task["exact_sessions"],
                "manifest_sha256": manifest.identity_sha256,
                "events": len(events),
                "manifest_path": str(path),
            }
        )
    payload = {
        "schema_version": 1,
        "kind": "exq001_sse_official_capture",
        "queue_sha256": args.queue_sha256,
        "task_count": len(results),
        "results": results,
        "formal_pit_status": "BLOCKED_DATA",
        "formal_research_status": "BLOCKED_DATA",
        "csi500": "NOT_STARTED",
    }
    identity = write_blob(args.result_root / "sse_official_capture", canonical(payload))
    print(json.dumps({"receipt_sha256": identity, "tasks": len(results)}, sort_keys=True))


if __name__ == "__main__":
    main()
