"""Translate RQAlpha vendor actions into the existing local paper ledger contract."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
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


def load_no_participation_overrides(path: Path) -> set[tuple[str, date]]:
    """Load evidence-backed rights issues that credit no synthetic cash or shares."""
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("corporate-action override file is invalid")
    events = payload.get("events")
    if not isinstance(events, list):
        raise ValueError("corporate-action overrides require an event list")
    output: set[tuple[str, date]] = set()
    for item in events:
        if (
            not isinstance(item, dict)
            or item.get("kind") != "rights_issue"
            or item.get("policy") != "no_participation_no_synthetic_cash_or_shares"
            or len(str(item.get("source_sha256", ""))) != 64
        ):
            raise ValueError("unsupported corporate-action override")
        output.add((str(item["symbol"]), date.fromisoformat(str(item["effective_date"]))))
    return output


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
