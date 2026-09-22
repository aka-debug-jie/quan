"""Signal-source attribution helper tests."""

import pandas as pd
import pytest

from quant_stack_v3.upgrade_artifacts import _rank_persistence


def test_rank_persistence_preserves_fixed_top_membership() -> None:
    rows = []
    for ordinal in (0, 1):
        for rank in range(1, 51):
            rows.append(
                {
                    "session": pd.Timestamp("2020-01-02") + pd.Timedelta(days=ordinal),
                    "symbol": f"sh{600000 + rank:06d}",
                    "session_ordinal": ordinal,
                    "score": float(51 - rank),
                    "score_rank": rank,
                }
            )
    result = _rank_persistence(pd.DataFrame(rows))
    assert result["1"]["mean_rank_correlation"] == pytest.approx(1.0)
    assert result["1"]["mean_top20_survival"] == 1.0
    assert result["1"]["mean_top50_survival"] == 1.0
