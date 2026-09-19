"""Content-address official execution-rule sources for EXQ-001."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import cast
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import yaml

from quant_stack_v2.dev_contract import canonical, write_blob

Fetcher = Callable[[str], tuple[bytes, dict[str, str]]]
HOSTS = {"www.csrc.gov.cn", "www.sse.com.cn", "www.szse.cn", "investor.szse.cn"}


def capture(
    source_path: Path, artifact_root: Path, *, allow_network: bool, fetcher: Fetcher | None = None
) -> dict[str, object]:
    """Capture each configured official source once, preserving all byte identities."""
    if not allow_network:
        raise ValueError("--allow-network is required")
    config = yaml.safe_load(source_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or config.get("status") != "PENDING_CAPTURE_AND_DATE_BINDING":
        raise ValueError("invalid EXQ rule-source contract")
    captured = []
    for item in config["sources"]:
        url = item["url"]
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in HOSTS:
            raise ValueError("non-official rule source")
        body, headers = (fetcher or _fetch)(url)
        digest = sha256(body).hexdigest()
        write_blob(artifact_root / "bodies", body, ".bin")
        receipt = canonical(
            {
                "source_id": item["id"],
                "url": url,
                "sha256": digest,
                "retrieved_at_utc": datetime.now(UTC).isoformat(),
                "http_metadata": headers,
            }
        )
        receipt_sha = write_blob(artifact_root / "receipts", receipt)
        captured.append({"id": item["id"], "body_sha256": digest, "receipt_sha256": receipt_sha})
    return {
        "schema_version": 1,
        "kind": "exq001_official_rule_source_capture",
        "source_contract_sha256": sha256(source_path.read_bytes()).hexdigest(),
        "status": "OFFICIAL_SOURCE_BYTES_CAPTURED_DATE_BINDING_PENDING",
        "sources": captured,
        "formal_pit_status": "BLOCKED_DATA",
        "formal_research_status": "BLOCKED_DATA",
        "csi500": "NOT_STARTED",
    }


def _fetch(url: str) -> tuple[bytes, dict[str, str]]:
    with urlopen(
        Request(url, headers={"User-Agent": "quant-stack-v2/1.0"}), timeout=30
    ) as response:
        return bytes(response.read()), {
            key.lower(): value for key, value in response.headers.items()
        }


def main() -> None:
    """Persist official source receipt after explicit network approval."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--result-root", type=Path, required=True)
    parser.add_argument("--allow-network", action="store_true")
    args = parser.parse_args()
    result = capture(args.sources, args.artifact_root, allow_network=args.allow_network)
    identity = write_blob(args.result_root, canonical(result))
    sources = cast(list[object], result["sources"])
    print(json.dumps({"receipt_sha256": identity, "sources": len(sources)}, sort_keys=True))


if __name__ == "__main__":
    main()
