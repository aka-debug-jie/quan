"""Offline scope tests for EXQ-001 bounded historical raw capture."""

from datetime import date

import pytest

from quant_stack_v2.exq001 import EXQ001Error
from quant_stack_v2.exq_akshare_history_capture import scope_requests


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
