"""Non-promoting local matching of released SZSE date labels to reviewed notices."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from hashlib import sha256
from pathlib import Path
from typing import Any

from quant_stack_v2.szse_history import apply_histories, load_histories
from quant_stack_v2.szse_issuer_supplement import load_claims
from quant_stack_v2.szse_lifecycle import apply_delistings, load_delistings
from quant_stack_v2.szse_verification import persist_report

RELEASED_DATES_SHA256 = "169b28c92d4fc00325e6f4b06aa560c9a16e9ad2b674102a5ec61b5ec0cae211"


def match_dates(
    dates_path: Path,
    manifest_path: Path,
    history_path: Path | None = None,
    lifecycle_path: Path | None = None,
) -> dict[str, Any]:
    """Match every released date; retain conflicts and require final sealed replay."""
    body = dates_path.read_bytes()
    if sha256(body).hexdigest() != RELEASED_DATES_SHA256:
        raise ValueError("released dates SHA-256 mismatch")
    source = json.loads(body)
    if source["scope"] != "LOCAL_SZSE_MATCHING_DATES_ONLY_NON_PROMOTING":
        raise ValueError("unexpected released-date scope")
    claims, manifest_digest = load_claims(manifest_path)
    seen: set[tuple[str, str]] = set()
    counts: Counter[str] = Counter()
    added: Counter[str] = Counter()
    results = []
    for symbol, session, baseline in source["rows"]:
        if (symbol, session) in seen:
            raise ValueError("duplicate released session")
        seen.add((symbol, session))
        if baseline not in {"OFFICIAL_SUSPENDED", "UNEXPLAINED", "CONFLICT"}:
            raise ValueError("unexpected monthly classification")
        relevant = [c for c in claims if c["symbol"] == symbol]
        matching = [
            c for c in relevant if c["first_full_session"] <= session <= c["last_full_session"]
        ]
        conflict = any(c["resume_date"] == session for c in relevant) or any(
            a["start_date"] == b["start_date"]
            and a["resume_date"] != b["resume_date"]
            and a["start_date"] <= session <= max(a["resume_date"], b["resume_date"])
            for a in relevant
            for b in relevant
        )
        label = baseline
        if conflict:
            label = "CONFLICT"
        elif baseline == "UNEXPLAINED" and matching:
            label = "ISSUER_CONFIRMED_SUSPENDED"
            added[symbol] += 1
        counts[label] += 1
        results.append([symbol, session, label])
    history_changes: list[dict[str, Any]] = []
    if history_path is not None:
        results, history_changes = apply_histories(results, load_histories(history_path), claims)
        counts = Counter(r[2] for r in results)
    if lifecycle_path is not None:
        results = apply_delistings(results, load_delistings(lifecycle_path))
        counts = Counter(r[2] for r in results)
        post = {(s, d) for s, d, label in results if label == "POST_DELISTING"}
        history_changes = [c for c in history_changes if (c["symbol"], c["session"]) not in post]
        added = Counter(s for s, _, label in results if label == "ISSUER_CONFIRMED_SUSPENDED")
    return {
        "schema_version": 1,
        "scope": "LOCAL_SZSE_MATCHING_ONLY_NON_PROMOTING",
        "released_dates_sha256": sha256(body).hexdigest(),
        "source_report_sha256": source["source_report_sha256"],
        "manifest_sha256": manifest_digest,
        "matching_source_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "supplement_source_sha256": sha256(
            Path(__file__).with_name("szse_issuer_supplement.py").read_bytes()
        ).hexdigest(),
        "missing_sessions": len(results),
        "covered_sessions": counts["OFFICIAL_SUSPENDED"]
        + counts["ISSUER_CONFIRMED_SUSPENDED"]
        + counts["ISSUER_CONFIRMED_HISTORY"]
        + counts["POST_DELISTING"],
        "post_delisting_sessions": counts["POST_DELISTING"],
        "lifecycle_manifest_sha256": lifecycle_path.stem if lifecycle_path else None,
        "lifecycle_source_sha256": sha256(
            Path(__file__).with_name("szse_lifecycle.py").read_bytes()
        ).hexdigest()
        if lifecycle_path
        else None,
        "uncovered_sessions": counts["UNEXPLAINED"] + counts["CONFLICT"],
        "conflict_sessions": counts["CONFLICT"],
        "newly_explained_sessions": sum(added.values()),
        "newly_explained_by_symbol": dict(sorted(added.items())),
        "history_manifest_sha256": history_path.stem if history_path else None,
        "history_source_sha256": sha256(
            Path(__file__).with_name("szse_history.py").read_bytes()
        ).hexdigest(),
        "monthly_index_sha256": "2140ec9a8ca8e17a542a7d8337ed3d672f655c86acf3446d82d8bc691b662ac1",
        "history_explained_sessions": len(history_changes),
        "history_explained_by_symbol": dict(Counter(r["symbol"] for r in history_changes)),
        "columns": ["symbol", "session", "classification"],
        "rows": results,
        "gap_gate": "BLOCKED_DATA",
        "membership_gate": "BLOCKED_DATA",
        "interpretation": "LOCAL_MATCHING_ONLY_FINAL_SEALED_REPLAY_REQUIRED",
    }


def main() -> None:
    """Archive a complete local match and print a reduced status."""
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("dates", "manifest", "output-root"):
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument("--history", type=Path)
    parser.add_argument("--lifecycle", type=Path)
    args = parser.parse_args()
    result = match_dates(args.dates, args.manifest, args.history, args.lifecycle)
    path = persist_report(result, args.output_root)
    print(json.dumps({k: v for k, v in result.items() if k != "rows"} | {"report_path": str(path)}))


if __name__ == "__main__":
    main()
