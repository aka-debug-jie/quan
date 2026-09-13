"""Release only six securities' member intervals; never release price/feature data."""

import hashlib
import json
from datetime import date
from pathlib import Path

ROOT = Path("/srv/quant-v2/sealed_holdout")
SYMBOLS = {"sh600005", "sh600832", "sh600837", "sh601299", "sh601989", "sz000562"}


def project(body: bytes) -> list[dict[str, str]]:
    """Allowlist symbols and ISO interval dates from the Qlib instrument text."""
    result = []
    for line in body.decode("utf-8").splitlines():
        fields = line.split()
        if not fields or fields[0].lower() not in SYMBOLS:
            continue
        if len(fields) != 3:
            raise ValueError("unexpected target instrument row")
        start, end = date.fromisoformat(fields[1]), date.fromisoformat(fields[2])
        if end < start:
            raise ValueError("invalid member interval")
        result.append(
            dict(
                symbol=fields[0].lower(),
                effective_from=start.isoformat(),
                effective_to=end.isoformat(),
            )
        )
    return sorted(result, key=lambda r: (r["symbol"], r["effective_from"]))


def main() -> None:
    """Find the unique CSI300 metadata file and emit only the specified six symbols."""
    paths = list(ROOT.rglob("csi300.txt"))
    paths = [p for p in paths if p.parent.name == "instruments"]
    if len(paths) != 1:
        raise ValueError("expected exactly one sealed instruments/csi300.txt")
    body = paths[0].read_bytes()
    print(
        json.dumps(
            dict(
                schema_version=1,
                scope="SIX_CSI300_ANOMALY_INTERVALS_NO_PRICES",
                source_relative_path=str(paths[0].relative_to(ROOT)),
                source_sha256=hashlib.sha256(body).hexdigest(),
                rows=project(body),
                membership_gate="BLOCKED_DATA",
            ),
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
