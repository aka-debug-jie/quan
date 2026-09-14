"""Replay archived SZSE monthly evidence against the exact EXQ queue."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from quant_stack_v2.dev_contract import canonical, read_blob, write_blob
from quant_stack_v2.szse_monthly import load_months
from quant_stack_v2.szse_verification import match_day


def main() -> None:
    """Persist monthly matches and issuer-notice tasks without redownloading evidence."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue-root", type=Path, required=True)
    parser.add_argument("--queue-sha256", required=True)
    parser.add_argument("--monthly-index", type=Path, required=True)
    parser.add_argument("--result-root", type=Path, required=True)
    args = parser.parse_args()
    queue = json.loads(read_blob(args.queue_root, args.queue_sha256))
    events = load_months(args.monthly_index)
    by_symbol: dict[str, list[Any]] = defaultdict(list)
    for event in events:
        by_symbol[event.symbol].append(event)
    rows = []
    issuer_tasks = []
    for task in queue["tasks"]:
        if task["exchange"] != "SZSE":
            continue
        matched = [
            match_day(by_symbol[task["symbol"]], date.fromisoformat(session))
            for session in task["exact_sessions"]
        ]
        rows.append({"symbol": task["symbol"], "matches": matched})
        unresolved = [
            item["session"] for item in matched if item["classification"] != "OFFICIAL_SUSPENDED"
        ]
        if unresolved:
            issuer_tasks.append(
                {
                    "symbol": task["symbol"],
                    "exact_sessions": unresolved,
                    "required_notice_kinds": [
                        "SUSPENSION_OR_RESUMPTION",
                        "CORPORATE_ACTION_OR_EX_RIGHT",
                        "RISK_WARNING_STATUS",
                    ],
                    "source": "CNINFO_OR_EXCHANGE_ISSUER_NOTICE",
                }
            )
    payload = {
        "schema_version": 1,
        "kind": "exq001_szse_archived_monthly_replay",
        "queue_sha256": args.queue_sha256,
        "monthly_index_sha256": args.monthly_index.stem,
        "task_count": len(rows),
        "issuer_task_count": len(issuer_tasks),
        "matches": rows,
        "issuer_notice_tasks": issuer_tasks,
        "formal_pit_status": "BLOCKED_DATA",
        "formal_research_status": "BLOCKED_DATA",
        "csi500": "NOT_STARTED",
    }
    identity = write_blob(args.result_root / "szse_monthly_replay", canonical(payload))
    print(
        json.dumps(
            {"receipt_sha256": identity, "tasks": len(rows), "issuer_tasks": len(issuer_tasks)},
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
