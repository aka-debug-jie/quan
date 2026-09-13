"""Export only fixed SZSE missing-date labels; stdout is captured by the caller."""

import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path

SOURCE_SHA = "b31fc67f7707cb728f1606b45ce909e0d1907991e62075be050b95a3ad186873"
SOURCE = Path(
    "/srv/quant-v2/sealed_holdout/artifacts/v2/free_suspension/"
    "szse_monthly_verification/" + SOURCE_SHA + ".json"
)


def project(body: bytes) -> dict:
    """Allowlist date labels, never copy arbitrary source fields or evidence."""
    if hashlib.sha256(body).hexdigest() != SOURCE_SHA:
        raise ValueError("fixed source SHA-256 mismatch")
    report = json.loads(body)
    rows = []
    seen = set()
    counts = Counter()
    for item in report["results"]:
        symbol = item["task"]["symbol"]
        if len(symbol) != 8 or not symbol.startswith("sz") or not symbol[2:].isdigit():
            raise ValueError("unexpected symbol")
        for entry in item["dates"]:
            session = date.fromisoformat(entry["session"]).isoformat()
            label = entry["classification"]
            if label not in {"OFFICIAL_SUSPENDED", "UNEXPLAINED", "CONFLICT"}:
                raise ValueError("unexpected classification")
            if (symbol, session) in seen:
                raise ValueError("duplicate session")
            seen.add((symbol, session))
            counts[label] += 1
            rows.append([symbol, session, label])
    if len(rows) != 8093 or counts != {"OFFICIAL_SUSPENDED": 2066, "UNEXPLAINED": 6027}:
        raise ValueError("unexpected baseline counts")
    return {
        "schema_version": 1,
        "scope": "LOCAL_SZSE_MATCHING_DATES_ONLY_NON_PROMOTING",
        "source_report_sha256": SOURCE_SHA,
        "columns": ["symbol", "session", "monthly_classification"],
        "rows": sorted(rows),
        "gap_gate": "BLOCKED_DATA",
        "membership_gate": "BLOCKED_DATA",
        "interpretation": "LOCAL_MATCHING_ONLY_FINAL_SEALED_REPLAY_REQUIRED",
    }


if __name__ == "__main__":
    print(json.dumps(project(SOURCE.read_bytes()), separators=(",", ":")))
