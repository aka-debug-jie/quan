"""Bounded CNINFO discovery/PDF archive for EXQ issuer-notice tasks."""

from __future__ import annotations

import argparse
import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import cast

from quant_stack_v2.cninfo_provider import archive_pdf, discover
from quant_stack_v2.dev_contract import canonical, read_blob, write_blob

KEYWORDS = re.compile(r"停牌|复牌|除权|除息|风险警示|\*?ST")
REJECTED = re.compile(r"取消|撤回|作废")


def _candidates(rows: list[dict[str, object]]) -> list[dict[str, str]]:
    """Retain title candidates only; this does not verify a suspension claim."""
    selected = []
    for row in rows:
        title, url = row.get("announcementTitle"), row.get("adjunctUrl")
        if (
            isinstance(title, str)
            and isinstance(url, str)
            and KEYWORDS.search(title)
            and not REJECTED.search(title)
        ):
            selected.append({"title": title, "adjunct_url": url})
    return selected


def main() -> None:
    """Run one fixed CNINFO discovery window per issuer task."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay-root", type=Path, required=True)
    parser.add_argument("--replay-sha256", required=True)
    parser.add_argument("--sealed-root", type=Path, required=True)
    parser.add_argument("--result-root", type=Path, required=True)
    parser.add_argument("--allow-network", action="store_true")
    args = parser.parse_args()
    replay = json.loads(read_blob(args.replay_root, args.replay_sha256))
    tasks = cast(list[dict[str, object]], replay["issuer_notice_tasks"])
    rows: list[dict[str, object]] = []
    for task in tasks:
        symbol = cast(str, task["symbol"])
        sessions = [date.fromisoformat(item) for item in cast(list[str], task["exact_sessions"])]
        start, end = min(sessions) - timedelta(days=30), max(sessions) + timedelta(days=30)
        try:
            catalog = discover(
                args.sealed_root / "artifacts/v2/exq001_candidate_scope/cninfo",
                symbol,
                start.isoformat(),
                end.isoformat(),
                allow_network=args.allow_network,
            )
            candidates = _candidates(cast(list[dict[str, object]], catalog["announcements"]))
            pdfs = [
                {
                    **item,
                    **archive_pdf(
                        args.sealed_root / "artifacts/v2/exq001_candidate_scope/cninfo",
                        item["adjunct_url"],
                        allow_network=args.allow_network,
                    ),
                }
                for item in candidates
            ]
            rows.append(
                {"symbol": symbol, "catalog_sha256": catalog["catalog_sha256"], "pdfs": pdfs}
            )
        except (ValueError, OSError) as error:
            rows.append({"symbol": symbol, "error": str(error)})
    payload = {
        "schema_version": 1,
        "kind": "exq001_cninfo_issuer_discovery",
        "replay_sha256": args.replay_sha256,
        "status": "DISCOVERY_COMPLETE",
        "tasks": rows,
        "formal_pit_status": "BLOCKED_DATA",
        "formal_research_status": "BLOCKED_DATA",
        "csi500": "NOT_STARTED",
    }
    identity = write_blob(args.result_root / "cninfo_issuer_discovery", canonical(payload))
    print(json.dumps({"receipt_sha256": identity, "tasks": len(rows)}, sort_keys=True))


if __name__ == "__main__":
    main()
