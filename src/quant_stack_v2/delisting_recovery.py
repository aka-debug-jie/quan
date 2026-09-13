"""Archive SSE delisting notices and classify residuals without changing membership."""

from __future__ import annotations

import argparse
import gzip
import json
import re
import subprocess
from datetime import UTC, datetime
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from quant_stack.snapshot import write_immutable

BASE = "https://www.sse.com.cn/"
SOURCES = {
    "sh600005": BASE + "disclosure/announcement/listing/c/c_20170208_4235564.shtml",
    "sh601299": BASE + "disclosure/announcement/general/c/c_20150910_3979290.shtml",
    "sh600837": BASE + "disclosure/announcement/listing/stock/c/c_20250226_10773005.shtml",
    "sh601989": BASE + "disclosure/announcement/listing/stock/c/c_20250829_10790128.shtml",
    "sh600832": BASE + "disclosure/announcement/general/c/c_20150910_3979291.shtml",
}


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _json(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        + b"\n"
    )


def parse_notice(text: str, symbol: str) -> str:
    """Extract an explicit delisting effective date, not a decision/publication date."""
    text = re.sub(r"\s+", "", text)
    if symbol[2:] not in text or "终止上市" not in text:
        raise ValueError("notice identity or subject not verified")
    patterns = (
        r"自(\d{4})年(\d{1,2})月(\d{1,2})日起终止其股票",
        r"将在(\d{4})年(\d{1,2})月(\d{1,2})日对.{0,30}?股票予以摘牌",
        r"摘牌日期[\uFF1A:](\d{4})年(\d{1,2})月(\d{1,2})日",
    )
    dates = {
        datetime(int(y), int(m), int(d)).date().isoformat()
        for pattern in patterns
        for y, m, d in re.findall(pattern, text)
    }
    if len(dates) != 1:
        raise ValueError("effective date absent or conflicting")
    return dates.pop()


def capture(root: Path, *, allow_network: bool) -> Path:
    """Preserve original official bytes and explicit failures with transport receipts."""
    if not allow_network:
        raise ValueError("--allow-network required")
    root = root.resolve()
    entries: dict[str, Any] = {}
    for symbol, url in SOURCES.items():
        receipt: dict[str, Any] = {"url": url, "retrieved_at": datetime.now(UTC).isoformat()}
        try:
            with urlopen(url, timeout=20) as response:
                raw = bytes(response.read())
                receipt.update(
                    http_status=response.status,
                    final_url=response.url,
                    headers=dict(response.headers.items()),
                )
            digest = sha256(raw).hexdigest()
            path = root / digest / ("notice.pdf" if raw.startswith(b"%PDF-") else "notice.html")
            write_immutable(path, raw)
            receipt.update(raw_sha256=digest, raw_path=str(path))
            decoded = gzip.decompress(raw) if raw.startswith(b"\x1f\x8b") else raw
            if decoded.startswith(b"%PDF-"):
                path = root / digest / "decoded.pdf"
                write_immutable(path, decoded)
                text = subprocess.check_output(["pdftotext", "-layout", str(path), "-"], text=True)
            else:
                parser = _Text()
                parser.feed(decoded.decode("utf-8"))
                text = " ".join(parser.parts)
            effective = parse_notice(text, symbol)
            entries[symbol] = {
                "effective_date": effective,
                "raw_sha256": digest,
                "raw_path": receipt["raw_path"],
                "url": url,
                "parser_version": "1",
                "status": "VERIFIED",
            }
        except (OSError, ValueError, subprocess.CalledProcessError) as error:
            entries[symbol] = {"status": "UNEXPLAINED", "reason": str(error), "url": url}
            receipt["error"] = str(error)
        receipt_bytes = _json(receipt)
        receipt_path = root / "receipts" / (sha256(receipt_bytes).hexdigest() + ".json")
        write_immutable(receipt_path, receipt_bytes)
        entries[symbol]["receipt_path"] = str(receipt_path)
    body = _json(
        {
            "entries": entries,
            "parser_source_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        }
    )
    output = root / "manifests" / (sha256(body).hexdigest() + ".json")
    write_immutable(output, body)
    print(str(output))
    return output


def reclassify(previous: dict[str, Any], entries: dict[str, Any]) -> dict[str, Any]:
    """Classify from the effective date inclusive; retain every original member date."""
    results = []
    for row in previous["results"]:
        symbol = row["task"]["symbol"]
        entry = entries.get(symbol, {})
        effective = entry.get("effective_date") if entry.get("status") == "VERIFIED" else None
        # Reclassify even previously suspension-covered dates on/after delisting.
        dates = sorted(row["covered_dates"] + row["uncovered_dates"])
        post = [d for d in dates if effective and d >= effective]
        suspended = [d for d in row["covered_dates"] if d not in post]
        unresolved = [d for d in row["uncovered_dates"] if d not in post]
        results.append(
            {
                "task": row["task"],
                "post_delisting": post,
                "official_suspended": suspended,
                "unexplained": unresolved,
                "source_conflict": row["status"] == "CONFLICT",
                "delisting_evidence": entry,
            }
        )
    unexplained = sum(len(r["unexplained"]) for r in results)
    conflicts = sum(r["source_conflict"] for r in results)
    return {
        "scope": "SSE_ONLY",
        "results": results,
        "post_delisting": sum(len(r["post_delisting"]) for r in results),
        "official_suspended": sum(len(r["official_suspended"]) for r in results),
        "unexplained": unexplained,
        "conflict_intervals": conflicts,
        "gap_gate": "PASS" if not unexplained and not conflicts else "BLOCKED_DATA",
        "membership_gate": "BLOCKED_DATA",
        "membership_reason": "CSI_OFFICIAL_ADJUSTMENT_DATES_NOT_VERIFIED",
        "membership_anomalies": [r["task"] for r in results if r["post_delisting"]],
    }


def main() -> None:
    """Capture public notices or generate a new offline residual report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    if args.previous is None:
        capture(args.root, allow_network=args.allow_network)
        return
    if args.manifest is None:
        parser.error("--manifest required for offline classification")
    for path in (args.previous, args.manifest):
        if path.stem != sha256(path.read_bytes()).hexdigest():
            raise ValueError("input report hash mismatch")
    manifest = json.loads(args.manifest.read_bytes())
    for symbol, entry in manifest["entries"].items():
        if entry["status"] == "VERIFIED":
            if (
                entry["url"] != SOURCES[symbol]
                or sha256(Path(entry["raw_path"]).read_bytes()).hexdigest() != entry["raw_sha256"]
            ):
                raise ValueError("archived evidence mismatch")
            original = Path(entry["raw_path"]).read_bytes()
            decoded = gzip.decompress(original) if original.startswith(b"\x1f\x8b") else original
            parser_text = _Text()
            parser_text.feed(decoded.decode("utf-8"))
            if parse_notice(" ".join(parser_text.parts), symbol) != entry["effective_date"]:
                raise ValueError("effective date differs from archived notice")
    result = reclassify(json.loads(args.previous.read_bytes()), manifest["entries"])
    result.update(previous_sha256=args.previous.stem, evidence_sha256=args.manifest.stem)
    body = _json(result)
    output = args.root / (sha256(body).hexdigest() + ".json")
    write_immutable(output, body)
    print(
        json.dumps(
            {k: v for k, v in result.items() if k not in ("results", "membership_anomalies")}
            | {"report_path": str(output)}
        )
    )


if __name__ == "__main__":
    main()
