"""Create a non-promoting corporate-action review queue from archived EXQ PDFs."""

from __future__ import annotations

import json
import re
from hashlib import sha256
from pathlib import Path

from quant_stack_v2.dev_contract import canonical, write_blob

TITLE = re.compile(r"除权|除息|权益分派|换股|终止上市|吸收合并")


def build(pdf_review_path: Path) -> dict[str, object]:
    """Retain only title leads; values and dates remain unverified."""
    body = pdf_review_path.read_bytes()
    if sha256(body).hexdigest() != pdf_review_path.stem.split(".")[0]:
        raise ValueError("PDF review identity mismatch")
    source = json.loads(body)
    leads = [
        {
            "symbol": row["symbol"],
            "announcement_id": row["announcement_id"],
            "title": row["title"],
            "official_url": row["official_url"],
            "pdf_sha256": row["pdf_sha256"],
            "required_fields": ["event_type", "record_date", "ex_date", "cash_or_share_terms"],
        }
        for row in source["rows"]
        if row["status"] != "FAILED" and TITLE.search(row["title"])
    ]
    return {
        "schema_version": 1,
        "kind": "exq001_corporate_action_review_queue",
        "source_pdf_review_sha256": pdf_review_path.stem.split(".")[0],
        "status": "LEADS_ONLY_NOT_ACCOUNTING_EVIDENCE",
        "lead_count": len(leads),
        "leads": leads,
        "formal_pit_status": "BLOCKED_DATA",
        "formal_research_status": "BLOCKED_DATA",
        "csi500": "NOT_STARTED",
    }


def main() -> None:
    """Persist a content-addressed, non-promoting review queue."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf-review", type=Path, required=True)
    parser.add_argument("--result-root", type=Path, required=True)
    args = parser.parse_args()
    payload = build(args.pdf_review)
    identity = write_blob(args.result_root, canonical(payload))
    print(json.dumps({"queue_sha256": identity, "leads": payload["lead_count"]}, sort_keys=True))


if __name__ == "__main__":
    main()
