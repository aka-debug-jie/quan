"""Extract candidate issuer-notice anchors without asserting a suspension claim."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

from quant_stack_v2.dev_contract import canonical, read_blob, write_blob

PATTERN = re.compile(r"[^。]{0,100}(?:停牌|复牌|恢复交易)[^。]{0,100}[。]")


def main() -> None:
    """Extract page-numbered candidate sentences from hash-pinned CNINFO PDFs."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--discovery-root", type=Path, required=True)
    parser.add_argument("--discovery-sha256", required=True)
    parser.add_argument("--sealed-root", type=Path, required=True)
    parser.add_argument("--result-root", type=Path, required=True)
    args = parser.parse_args()
    discovery = json.loads(read_blob(args.discovery_root, args.discovery_sha256))
    candidates = []
    for task in discovery["tasks"]:
        for pdf in task.get("pdfs", []):
            path = (
                args.sealed_root
                / "artifacts/v2/exq001_candidate_scope/cninfo/cninfo_pdfs"
                / pdf["raw_sha256"]
                / "notice.pdf"
            )
            text = subprocess.run(
                ["/usr/bin/pdftotext", "-layout", str(path), "-"],
                check=True,
                capture_output=True,
                timeout=30,
            ).stdout.decode("utf-8", errors="replace")
            for page, value in enumerate(text.split("\f"), 1):
                for sentence in PATTERN.findall(value.replace("\n", "")):
                    candidates.append(
                        {
                            "symbol": task["symbol"],
                            "raw_sha256": pdf["raw_sha256"],
                            "official_url": pdf["official_url"],
                            "title": pdf["title"],
                            "page": page,
                            "anchor": sentence,
                        }
                    )
    payload = {
        "schema_version": 1,
        "kind": "exq001_cninfo_candidate_anchors",
        "discovery_sha256": args.discovery_sha256,
        "status": "CANDIDATE_ANCHORS_NOT_VERIFIED",
        "candidates": candidates,
        "formal_pit_status": "BLOCKED_DATA",
        "formal_research_status": "BLOCKED_DATA",
        "csi500": "NOT_STARTED",
    }
    identity = write_blob(args.result_root / "cninfo_candidate_anchors", canonical(payload))
    print(json.dumps({"receipt_sha256": identity, "candidates": len(candidates)}, sort_keys=True))


if __name__ == "__main__":
    main()
