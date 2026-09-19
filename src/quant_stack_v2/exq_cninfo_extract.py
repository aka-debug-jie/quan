"""Extract candidate issuer-notice anchors without asserting a suspension claim."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from hashlib import sha256
from pathlib import Path

from quant_stack_v2.dev_contract import canonical, read_blob, write_blob


def extract_pdf(path: Path, expected_sha256: str) -> list[dict[str, object]]:
    """Check actual PDF bytes and retain entire sentences, including planned wording."""
    if path.is_symlink() or sha256(path.read_bytes()).hexdigest() != expected_sha256:
        raise ValueError("PDF SHA-256 mismatch or symlink")
    text = subprocess.run(
        ["/usr/bin/pdftotext", "-layout", str(path), "-"],
        check=True,
        capture_output=True,
        timeout=30,
    ).stdout.decode("utf-8")
    anchors: list[dict[str, object]] = []
    for page, value in enumerate(text.split("\f"), 1):
        # Never truncate a sentence prefix: it may contain a negation or a plan.
        for match in re.finditer(r"[^。!?]+[。!?]|[^。!?]+$", value):
            sentence = match.group().strip()
            if re.search(r"停牌|复牌|恢复交易|除权|除息|权益分派|风险警示", sentence):
                anchors.append({"page": page, "anchor": sentence})
    return anchors


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
            for anchor in extract_pdf(path, pdf["raw_sha256"]):
                candidates.append(
                    {
                        "symbol": task["symbol"],
                        "raw_sha256": pdf["raw_sha256"],
                        "official_url": pdf["official_url"],
                        "title": pdf["title"],
                        **anchor,
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
