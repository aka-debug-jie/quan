"""Synthetic corrected-runner and independent-reference integration."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quant_stack_v3.protocol import ResearchSpec, load_protocol
from quant_stack_v3.upgrade_reference import audit_reference_run
from quant_stack_v3.upgrade_runner import UpgradeInputs, UpgradeRunSpec, run_upgrade_strategy

h5py = pytest.importorskip("h5py")
ROOT = Path(__file__).parents[1]


def test_corrected_runner_matches_independent_reference(tmp_path: Path) -> None:
    protocol = load_protocol(ROOT / "configs/v3/cn_historical_research_v3.yaml")
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
    np.save(bundle / "trading_dates.npy", np.asarray([int(x.strftime("%Y%m%d")) for x in sessions]))
    for name in ("dividends.h5", "split_factor.h5", "ex_cum_factor.h5"):
        with h5py.File(bundle / name, "w"):
            pass
    (bundle / "share_transformation.json").write_text("{}", encoding="utf-8")
    bars_rows: list[dict[str, object]] = []
    score_rows: list[dict[str, object]] = []
    for day, session in enumerate(sessions):
        for rank in range(1, 26):
            symbol = f"sh{600000 + rank:06d}"
            price = 10.0 + rank / 10 + day / 100
            bars_rows.append(
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
                    "score_rank": rank,
                    "liquidity_rank": rank,
                    "mean_amount_20": 20_000_000,
                }
            )
    bars_path = tmp_path / "bars.parquet"
    scores_path = tmp_path / "scores.parquet"
    pd.DataFrame(bars_rows).to_parquet(bars_path, index=False)
    pd.DataFrame(score_rows).to_parquet(scores_path, index=False)
    artifacts = tmp_path / "artifacts"
    inputs = UpgradeInputs(
        bundle,
        "a" * 64,
        bars_path,
        scores_path,
        artifacts,
        ROOT / "configs/v3/cn_historical_research_v3.yaml",
        ROOT / "configs/upgrade/cn_quant_research_upgrade_v1.yaml",
        ROOT / "configs/v3/corporate_action_overrides_v1.yaml",
    )
    result_path, result = run_upgrade_strategy(
        protocol,
        UpgradeRunSpec(
            "B00_LIQ20_D20__REAL_T1_1M",
            "B00_LIQ20_D20",
            "REAL_T1_1M",
            Decimal("1000000"),
            1,
            "real",
        ),
        inputs,
    )
    assert result["HISTORICAL_RUN_STATUS"] == "COMPLETE_REAL_DATA"
    assert result_path.exists()
    reference_path, reference = audit_reference_run(
        primary_run_root=result_path.parent,
        bundle_root=bundle,
        bundle_sha256="a" * 64,
        bars_path=bars_path,
        base_protocol=protocol,
        output_root=artifacts,
    )
    assert reference["status"] == "INDEPENDENT_ECONOMIC_REFERENCE_PASS"
    assert reference_path.exists()
