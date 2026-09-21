"""Synthetic end-to-end validation of the isolated historical runner."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quant_stack_v3.protocol import ResearchSpec, load_protocol
from quant_stack_v3.runner import RunOptions, run_strategy

h5py = pytest.importorskip("h5py")
ROOT = Path(__file__).parents[1]


def test_real_runner_contract_fills_only_after_signal_and_reconciles(tmp_path: Path) -> None:
    protocol_path = ROOT / "configs/v3/cn_historical_research_v3.yaml"
    protocol = load_protocol(protocol_path)
    sessions = tuple(pd.bdate_range("2020-01-02", periods=6).date)
    protocol = protocol.model_copy(
        update={
            "research": ResearchSpec(
                start=sessions[0],
                end=sessions[-1],
                touched_development_end=sessions[-2],
                maximum_lookback_sessions=60,
                minimum_listing_sessions=252,
            )
        }
    )
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    np.save(
        bundle / "trading_dates.npy",
        np.asarray([int(item.strftime("%Y%m%d")) for item in sessions]),
    )
    for name in ("dividends.h5", "split_factor.h5", "ex_cum_factor.h5"):
        with h5py.File(bundle / name, "w"):
            pass
    (bundle / "share_transformation.json").write_text("{}", encoding="utf-8")
    bar_rows = []
    score_rows = []
    for day_index, session in enumerate(sessions):
        for symbol_index in range(25):
            symbol = f"sh{600000 + symbol_index:06d}"
            price = 10 + symbol_index / 10 + day_index / 100
            bar_rows.append(
                {
                    "session": pd.Timestamp(session),
                    "symbol": symbol,
                    "raw_open": price,
                    "raw_close": price + 0.01,
                    "limit_up": price * 1.1,
                    "limit_down": price * 0.9,
                    "suspended": False,
                    "board": "main",
                }
            )
            score_rows.append(
                {
                    "session": pd.Timestamp(session),
                    "symbol": symbol,
                    "score_rank": symbol_index + 1,
                    "liquidity_rank": symbol_index + 1,
                    "mean_amount_20": 20_000_000,
                }
            )
    bars = tmp_path / "bars.parquet"
    scores = tmp_path / "scores.parquet"
    pd.DataFrame(bar_rows).to_parquet(bars, index=False)
    pd.DataFrame(score_rows).to_parquet(scores, index=False)
    result_path, result = run_strategy(
        protocol,
        protocol_path,
        protocol.strategies[0],
        RunOptions(),
        bundle_root=bundle,
        bundle_sha256="a" * 64,
        bars_path=bars,
        scores_path=scores,
        artifact_root=tmp_path / "artifacts",
    )
    assert result["HISTORICAL_RUN_STATUS"] == "COMPLETE_REAL_DATA"
    assert result["RESEARCH_VALIDITY"] == "VALID_RETROSPECTIVE_DEVELOPMENT_COMPARISON"
    assert result["execution"]["fills"] == 20
    assert result["execution"]["direct_cost_total"] != "0"
    assert json.loads(result_path.read_text())["identities"]["ledger_events"] > 0
