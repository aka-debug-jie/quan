"""Translate RQAlpha vendor actions into the existing local paper ledger contract."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import yaml

from quant_stack.data.models import (
    CorporateActionEvent,
    CorporateActionKind,
    OfficialEvidence,
)

SOURCE_URL = "https://bundle.assets.ricequant.com/bundles_v4/rqbundle_202609.tar.bz2"


@dataclass(frozen=True)
class PositionTransfer:
    """One bundle-declared predecessor-to-successor share conversion."""

    effective_date: date
    predecessor: str
    successor: str
    ratio: Decimal


def load_actions(
    bundle_root: Path,
    *,
    bundle_sha256: str,
    start: date,
    end: date,
) -> tuple[
    dict[date, dict[str, tuple[CorporateActionEvent, ...]]],
    dict[date, tuple[PositionTransfer, ...]],
]:
    """Load dated cash, split, and code-conversion events from one verified bundle."""
    import h5py  # type: ignore

    by_date: dict[date, dict[str, list[CorporateActionEvent]]] = {}
    with h5py.File(bundle_root / "dividends.h5", "r") as handle:
        for provider_symbol in handle.keys():
            symbol = _symbol(provider_symbol)
            if symbol is None:
                continue
            for row in handle[provider_symbol][:]:
                effective = _optional_date(row["ex_dividend_date"])
                record = _optional_date(row["book_closure_date"])
                payment = _optional_date(row["payable_date"])
                announcement = _optional_date(row["announcement_date"])
                round_lot = Decimal(str(row["round_lot"]))
                cash = Decimal(str(row["dividend_cash_before_tax"]))
                if (
                    effective is None
                    or record is None
                    or payment is None
                    or round_lot <= 0
                    or cash <= 0
                    or not _overlaps((effective, record, payment), start, end)
                ):
                    continue
                action = CorporateActionEvent(
                    effective_date=effective,
                    kind=CorporateActionKind.CASH_DISTRIBUTION,
                    cash_per_unit=cash / round_lot,
                    evidence=_evidence(bundle_sha256, announcement or effective),
                    event_announcement_date=announcement,
                    record_date=record,
                    payment_date=payment,
                    retrospective_verification=True,
                )
                for session in {effective, record, payment}:
                    if start <= session <= end:
                        by_date.setdefault(session, {}).setdefault(symbol, []).append(action)
    with h5py.File(bundle_root / "split_factor.h5", "r") as handle:
        for provider_symbol in handle.keys():
            symbol = _symbol(provider_symbol)
            if symbol is None:
                continue
            for row in handle[provider_symbol][:]:
                effective = _optional_date(row["ex_date"])
                ratio = Decimal(str(row["split_factor"]))
                if effective is None or ratio <= 0 or not start <= effective <= end:
                    continue
                action = CorporateActionEvent(
                    effective_date=effective,
                    kind=CorporateActionKind.SHARE_SPLIT,
                    split_ratio=ratio,
                    evidence=_evidence(bundle_sha256, effective),
                    retrospective_verification=True,
                )
                by_date.setdefault(effective, {}).setdefault(symbol, []).append(action)
    actions = {
        session: {
            symbol: tuple(
                sorted(
                    values,
                    key=lambda item: (item.effective_date, item.kind.value),
                )
            )
            for symbol, values in sorted(symbols.items())
        }
        for session, symbols in sorted(by_date.items())
    }
    transfers = _load_transfers(bundle_root / "share_transformation.json", start, end)
    return actions, transfers


def unexplained_factor_events(
    bundle_root: Path,
    actions: dict[date, dict[str, tuple[CorporateActionEvent, ...]]],
    *,
    start: date,
    end: date,
) -> dict[date, tuple[str, ...]]:
    """Return factor changes not explained by a cash/split event in the vendor ledger."""
    import h5py

    known = {
        (symbol, action.effective_date)
        for symbols in actions.values()
        for symbol, values in symbols.items()
        for action in values
    }
    output: dict[date, list[str]] = {}
    with h5py.File(bundle_root / "ex_cum_factor.h5", "r") as handle:
        for provider_symbol in handle.keys():
            symbol = _symbol(provider_symbol)
            if symbol is None:
                continue
            for row in handle[provider_symbol][:]:
                effective = _optional_date(row["start_date"])
                if (
                    effective is not None
                    and start <= effective <= end
                    and (symbol, effective) not in known
                ):
                    output.setdefault(effective, []).append(symbol)
    return {session: tuple(sorted(set(symbols))) for session, symbols in sorted(output.items())}


def load_no_participation_overrides(
    path: Path, *, evidence_root: Path | None = None
) -> set[tuple[str, date]]:
    """Load verified rights issues without crediting synthetic cash or shares."""
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") not in {1, 2}:
        raise ValueError("corporate-action override file is invalid")
    inherited: set[tuple[str, date]] = set()
    if payload["schema_version"] == 2:
        if evidence_root is None:
            raise ValueError("closure evidence root is required")
        source = payload.get("inherits")
        if not isinstance(source, dict) or not isinstance(source.get("path"), str):
            raise ValueError("closure evidence must identify inherited overrides")
        inherited_path = (path.parent / source["path"]).resolve()
        if _file_sha256(inherited_path) != source.get("sha256"):
            raise ValueError("inherited corporate-action override hash differs")
        inherited = load_no_participation_overrides(inherited_path, evidence_root=evidence_root)
    events = payload.get("events")
    if not isinstance(events, list):
        raise ValueError("corporate-action overrides require an event list")
    output = set(inherited)
    for item in events:
        if (
            not isinstance(item, dict)
            or item.get("kind") != "rights_issue"
            or item.get("policy") != "no_participation_no_synthetic_cash_or_shares"
        ):
            raise ValueError("unsupported corporate-action override")
        if payload["schema_version"] == 1:
            if len(str(item.get("source_sha256", ""))) != 64:
                raise ValueError("legacy rights issue lacks source hash")
        else:
            _validate_closure_rights_issue(item, evidence_root)
        key = (str(item["symbol"]), date.fromisoformat(str(item["effective_date"])))
        if key in output:
            raise ValueError("duplicate corporate-action override")
        output.add(key)
    return output


def _validate_closure_rights_issue(item: dict[str, object], evidence_root: Path | None) -> None:
    if evidence_root is None:
        raise ValueError("closure evidence root is required")
    record = date.fromisoformat(str(item["registration_date"]))
    effective = date.fromisoformat(str(item["effective_date"]))
    listing = date.fromisoformat(str(item["listing_date"]))
    offered = Decimal(str(item["offered_ratio"]))
    price = Decimal(str(item["subscription_price"]))
    record_shares = int(str(item["record_shares"]))
    issued = int(str(item["actual_issued_shares"]))
    if (
        not record < effective < listing
        or offered <= 0
        or price <= 0
        or record_shares <= 0
        or issued <= 0
        or Decimal(issued) > Decimal(record_shares) * offered + 1
    ):
        raise ValueError("closure rights issue economics are invalid")
    documents = item.get("source_documents")
    if not isinstance(documents, list) or len(documents) < 2:
        raise ValueError("closure rights issue requires issue and result evidence")
    for document in documents:
        if not isinstance(document, dict):
            raise ValueError("closure evidence document must be a mapping")
        digest = str(document.get("sha256", ""))
        url = str(document.get("url", ""))
        pages = document.get("pages")
        if (
            len(digest) != 64
            or not url.startswith("https://")
            or not isinstance(pages, list)
            or not pages
        ):
            raise ValueError("closure evidence document metadata is incomplete")
        if not all(isinstance(page, int) and page > 0 for page in pages):
            raise ValueError("closure evidence page references are invalid")
        date.fromisoformat(str(document["published_on"]))
        source_path = evidence_root / "raw" / f"{digest}.pdf"
        if not source_path.is_file() or _file_sha256(source_path) != digest:
            raise ValueError("closure evidence source hash differs")
        with source_path.open("rb") as handle:
            if handle.read(4) != b"%PDF":
                raise ValueError("closure evidence source is not a PDF")


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _load_transfers(path: Path, start: date, end: date) -> dict[date, tuple[PositionTransfer, ...]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("share transformation payload must be a mapping")
    output: dict[date, list[PositionTransfer]] = {}
    for predecessor_raw, item in payload.items():
        if not isinstance(item, dict):
            raise ValueError("share transformation record must be a mapping")
        predecessor = _symbol(str(predecessor_raw))
        successor = _symbol(str(item.get("successor", "")))
        effective = date.fromisoformat(str(item["effective_date"]))
        ratio = Decimal(str(item["share_conversion_ratio"]))
        if predecessor is None:
            continue
        if predecessor is None or successor is None or ratio <= 0:
            raise ValueError("invalid share transformation record")
        if start <= effective <= end:
            output.setdefault(effective, []).append(
                PositionTransfer(effective, predecessor, successor, ratio)
            )
    return {
        session: tuple(sorted(values, key=lambda item: (item.predecessor, item.successor)))
        for session, values in sorted(output.items())
    }


def _evidence(bundle_sha256: str, published: date) -> OfficialEvidence:
    return OfficialEvidence(url=SOURCE_URL, sha256=bundle_sha256, published_on=published)


def _optional_date(value: object) -> date | None:
    try:
        integer = int(float(str(value)))
    except (OverflowError, ValueError):
        return None
    if integer <= 0:
        return None
    if integer > 99_999_999:
        integer //= 1_000_000
    text = f"{integer:08d}"
    try:
        return date(int(text[:4]), int(text[4:6]), int(text[6:]))
    except ValueError:
        return None


def _overlaps(values: tuple[date, ...], start: date, end: date) -> bool:
    return any(start <= item <= end for item in values)


def _symbol(value: str) -> str | None:
    if len(value) != 11 or not value[:6].isdigit():
        return None
    code = value[:6]
    if value.endswith(".XSHG") and code.startswith(("600", "601", "603", "605", "688", "689")):
        return "sh" + code
    if value.endswith(".XSHE") and code.startswith(
        ("000", "001", "002", "003", "300", "301", "302")
    ):
        return "sz" + code
    return None
