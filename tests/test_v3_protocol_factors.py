"""Frozen protocol and seven-factor equivalence tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quant_stack_v3.factors import build_scores
from quant_stack_v3.protocol import ALPHAS, load_protocol

ROOT = Path(__file__).parents[1]


def test_protocol_freezes_matrix_and_sealed_boundaries() -> None:
    protocol = load_protocol(ROOT / "configs/v3/cn_historical_research_v3.yaml")
    assert protocol.signal.alpha_ids == ALPHAS
    assert len(protocol.strategies) == 6
    assert "csi500" in protocol.forbidden_uses
    assert protocol.execution.earliest_delay_sessions == 1


def test_build_scores_uses_only_complete_causal_cross_section() -> None:
    protocol = load_protocol(ROOT / "configs/v3/cn_historical_research_v3.yaml")
    sessions = pd.bdate_range("2014-09-01", periods=320)
    rows: list[dict[str, object]] = []
    for symbol_index in range(300):
        for session_index, session in enumerate(sessions):
            trend = (symbol_index % 11 - 5) * 0.0004
            close = 10 + symbol_index / 20 + session_index * (0.01 + trend)
            rows.append(
                {
                    "session": session,
                    "symbol": f"sh{600000 + symbol_index:06d}",
                    "calc_high": close + 0.2 + symbol_index % 3 / 100,
                    "calc_low": close - 0.2,
                    "calc_close": close,
                    "calc_volume": 1_000_000 + symbol_index * 100 + session_index,
                    "amount": 20_000_000 + symbol_index * 10_000,
                    "st": False,
                    "suspended": False,
                    "session_ordinal": session_index,
                    "listed_sessions": 252 + session_index,
                }
            )
    frame = pd.DataFrame(rows)
    scores = build_scores(frame, protocol)
    assert not scores.empty
    last = scores.loc[scores.session == scores.session.max()]
    assert len(last) == 300
    assert last.score_rank.tolist() == list(range(1, 301))
    assert np.isfinite(last.loc[:, list(ALPHAS)].to_numpy()).all()


def test_missing_session_prevents_false_60_row_substitution() -> None:
    protocol = load_protocol(ROOT / "configs/v3/cn_historical_research_v3.yaml")
    sessions = pd.bdate_range("2014-01-01", periods=420)
    rows = []
    for symbol_index in range(300):
        for session_index, session in enumerate(sessions):
            if symbol_index == 0 and session_index == 350:
                continue
            close = 10 + symbol_index / 100 + session_index / 1000
            rows.append(
                {
                    "session": session,
                    "symbol": f"sh{600000 + symbol_index:06d}",
                    "calc_high": close + 0.1,
                    "calc_low": close - 0.1,
                    "calc_close": close,
                    "calc_volume": 1_000_000 + symbol_index,
                    "amount": 20_000_000 + symbol_index,
                    "st": False,
                    "suspended": False,
                    "session_ordinal": session_index,
                    "listed_sessions": 252 + session_index,
                }
            )
    scores = build_scores(pd.DataFrame(rows), protocol)
    affected = scores.loc[
        (scores.symbol == "sh600000")
        & (scores.session > sessions[350])
        & (scores.session <= sessions[350 + 59])
    ]
    assert affected.empty


def test_protocol_rejects_factor_drift(tmp_path: Path) -> None:
    source = ROOT / "configs/v3/cn_historical_research_v3.yaml"
    path = tmp_path / "drift.yaml"
    path.write_text(source.read_text().replace("CN_REV_001", "CN_MOM_001"), encoding="utf-8")
    with pytest.raises(ValueError, match="seven AF-003"):
        load_protocol(path)
