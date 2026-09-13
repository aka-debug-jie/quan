"""Offline parsing of immutable SZSE monthly suspension tables."""

from __future__ import annotations

import calendar
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse


class _Table(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self.row: list[str] = []
        self.cell: list[str] | None = None
        self.text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self.row = []
        elif tag in ("td", "th"):
            self.cell = []

    def handle_data(self, data: str) -> None:
        self.text.append(data)
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row:
            self.rows.append(self.row)
            self.row = []


@dataclass(frozen=True)
class MonthlyEvent:
    """One table row with exchange-local timestamps and immutable provenance."""

    symbol: str
    month: str
    start: datetime
    resume: datetime | None
    start_text: str
    start_is_intraday: bool
    reason: str
    raw_sha256: str
    official_url: str
    row_number: int

    @property
    def kind(self) -> str:
        """Distinguish open, intraday and closed multi-session records."""
        if self.resume is None:
            return "OPEN"
        if self.resume.date() == self.start.date():
            return "INTRADAY"
        return "CLOSED"

    def full_days(self, resume: datetime | None = None) -> tuple[date, date]:
        """Bound open evidence to its month; exclude partial start/resumption days."""
        first = date.fromisoformat(self.month + "-01")
        last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
        start = self.start.date()
        if self.start_is_intraday:
            start += timedelta(days=1)
        end_time = resume if resume is not None else self.resume
        if end_time is None:
            return max(start, first), last
        # Conservative even for a stated 15:00 resumption: exclude the resume date.
        end = end_time.date() - timedelta(days=1)
        if self.resume is None:
            return max(start, first), min(end, last)
        return start, end


def parse_month(raw: bytes, month: str, url: str) -> tuple[MonthlyEvent, ...]:
    """Validate a five-column SZSE table, decoding UTF-8 or strict GB18030."""
    first = date.fromisoformat(month + "-01")
    try:
        html = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        html = raw.decode("gb18030")
    table = _Table()
    table.feed(html)
    text = unicodedata.normalize("NFKC", "".join(table.text))
    if "证券停牌情况" not in text or f"({first:%Y.%m})" not in text:
        raise ValueError("table title/month mismatch")
    headers = ["代码", "证券简称", "停牌原因", "停牌时间", "复牌时间"]
    if (
        not table.rows
        or len(table.rows[0]) != 5
        or not all(value in cell for value, cell in zip(headers, table.rows[0], strict=True))
    ):
        raise ValueError("unexpected suspension table columns")
    events: list[MonthlyEvent] = []
    for row_number, row in enumerate(table.rows[1:], 2):
        if len(row) != 5 or re.fullmatch(r"\d{6}", row[0]) is None:
            raise ValueError(f"invalid table row {row_number}")
        unknown_intraday = row[3].endswith(" 盘中即时")
        start = datetime.strptime(
            row[3][:10] if unknown_intraday else row[3],
            "%Y/%m/%d" if unknown_intraday else "%Y/%m/%d %H:%M",
        )
        resume = (
            None if row[4] == "9999/12/31 00:00" else datetime.strptime(row[4], "%Y/%m/%d %H:%M")
        )
        if start.year == 9999 or (resume is not None and (resume.year == 9999 or resume <= start)):
            raise ValueError(f"invalid suspension timestamps at row {row_number}")
        events.append(
            MonthlyEvent(
                "sz" + row[0],
                month,
                start,
                resume,
                row[3],
                unknown_intraday or start.time() > time(9, 30),
                row[2],
                sha256(raw).hexdigest(),
                url,
                row_number,
            )
        )
    return tuple(events)


def load_months(index: Path) -> tuple[MonthlyEvent, ...]:
    """Verify the index and every raw table; resolve only archive-local hash paths."""
    body = index.read_bytes()
    if index.stem != sha256(body).hexdigest():
        raise ValueError("monthly index SHA-256 mismatch")
    payload = json.loads(body)
    months: set[str] = set()
    events: list[MonthlyEvent] = []
    for item in payload["months"]:
        month = item["month"]
        if month in months or item["status"] != "CAPTURED_NOT_QUALIFIED":
            raise ValueError("duplicate or unarchived month")
        months.add(month)
        source = item["table"]
        digest = source["sha256"]
        if re.fullmatch(r"[a-f0-9]{64}", digest) is None:
            raise ValueError("invalid table SHA-256")
        for field in ("url", "final_url"):
            url = urlparse(source[field])
            if url.scheme != "https" or url.hostname not in ("www.szse.cn", "docs.static.szse.cn"):
                raise ValueError("non-official table URL")
        raw = (index.parent / "raw" / digest / "body.html").read_bytes()
        if sha256(raw).hexdigest() != digest:
            raise ValueError("raw table SHA-256 mismatch")
        events.extend(parse_month(raw, month, source["url"]))
    if not months:
        raise ValueError("empty monthly archive")
    return tuple(events)
