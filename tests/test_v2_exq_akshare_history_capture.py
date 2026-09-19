"""Offline scope tests for EXQ-001 bounded historical raw capture."""

import json
from datetime import date
from pathlib import Path

import pytest

from quant_stack_v2.akshare_provider import AKShareManifest
from quant_stack_v2.exq001 import EXQ001Error
from quant_stack_v2.exq_akshare_history_capture import existing_manifests, scope_requests


def test_scope_requests_bind_every_frozen_symbol_to_the_one_approved_span() -> None:
    """The capture cannot add symbols or dates beyond the access manifest span."""
    assert scope_requests(("sh600001", "sz000001"), date(2019, 12, 30), date(2020, 1, 3)) == (
        ("sh600001", date(2019, 12, 30), date(2020, 1, 3)),
        ("sz000001", date(2019, 12, 30), date(2020, 1, 3)),
    )


def test_scope_requests_rejects_unordered_symbols() -> None:
    """A caller cannot rely on the capture to normalize a widened scope."""
    with pytest.raises(EXQ001Error, match="scope"):
        scope_requests(("sz000001", "sh600001"), date(2020, 1, 2), date(2020, 1, 3))


def test_existing_manifests_reuses_only_the_exact_approved_span(tmp_path: Path) -> None:
    """A daily capture cannot be reused for a wider historical request."""
    root = tmp_path / "akshare_eastmoney_manifests"
    exact = AKShareManifest("sz000001", "2020-01-02", "2020-01-03", (), "test", "a" * 64, 2)
    daily = AKShareManifest("sz000002", "2020-01-02", "2020-01-02", (), "test", "b" * 64, 1)
    for item in (exact, daily):
        path = root / item.identity_sha256 / "manifest.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "symbol": item.symbol,
                    "start_date": item.start_date,
                    "end_date": item.end_date,
                    "fields": list(item.fields),
                    "provider_version": item.provider_version,
                    "raw_sha256": item.raw_sha256,
                    "row_count": item.row_count,
                }
            )
        )
    assert existing_manifests(
        tmp_path,
        (
            ("sz000001", date(2020, 1, 2), date(2020, 1, 3)),
            ("sz000002", date(2020, 1, 2), date(2020, 1, 3)),
        ),
    ) == (exact,)
