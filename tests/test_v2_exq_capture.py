"""Offline tests for EXQ-001 bounded raw-provider request construction."""

from datetime import date

import pytest

from quant_stack_v2.exq_capture import EXQ001Error, _residual_requests


def test_residual_requests_compress_only_same_symbol_dates() -> None:
    """One provider envelope is emitted per actual residual-intersection symbol."""
    requests = _residual_requests(
        [
            {"symbol": "sz000001", "expected_session": "2020-01-06"},
            {"symbol": "sz000001", "expected_session": "2020-01-02"},
            {"symbol": "sh600001", "expected_session": "2020-01-03"},
        ]
    )
    assert requests == (
        ("sh600001", date(2020, 1, 3), date(2020, 1, 3)),
        ("sz000001", date(2020, 1, 2), date(2020, 1, 6)),
    )


def test_residual_requests_reject_missing_key() -> None:
    """The narrow capture cannot expand an incomplete residual row."""
    with pytest.raises(EXQ001Error, match="invalid"):
        _residual_requests([{"symbol": "sz000001"}])
