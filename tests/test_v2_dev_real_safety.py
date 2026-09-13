"""Safety regressions for the staged DEV-001 Qlib view."""

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from quant_stack_v2.dev_contract import Member
from quant_stack_v2.dev_real_staged_view import (
    _child,
    _project_features,
    _project_labels,
    corrected_members,
)


def _correction() -> tuple[tuple[Member, ...], dict[str, object]]:
    source = (
        *(
            Member(
                symbol=f"sh60000{index}",
                start=date(2015, 1, 1),
                end=date(2015, 2, 28),
            )
            for index in range(5)
        ),
        Member(symbol="sz000001", start=date(2015, 1, 1), end=date(2020, 12, 31)),
    )
    edits = [
        {
            "before": {
                "symbol": member.symbol,
                "effective_from": member.start.isoformat(),
                "effective_to": member.end.isoformat(),
            },
            "after": {
                "symbol": member.symbol,
                "effective_from": member.start.isoformat(),
                "effective_to": (member.end - timedelta(days=index + 1)).isoformat(),
            },
        }
        for index, member in enumerate(source[:5])
    ]
    return source, {
        "scope": "SIX_SYMBOL_END_BOUNDARY_RECONCILIATION_NOT_FULL_PIT",
        "membership_gate": "BLOCKED_DATA",
        "raw_member_file_modified": False,
        "official_end_boundary_edits": edits,
    }


def test_only_five_exact_member_end_edits_are_applied() -> None:
    source, correction = _correction()
    derived = corrected_members(source, correction)
    assert len(derived) == len(source)
    assert derived[-1] == source[-1]
    assert sum(left.end != right.end for left, right in zip(source, derived, strict=True)) == 5


def test_duplicate_member_edit_is_rejected() -> None:
    source, correction = _correction()
    edits = list(correction["official_end_boundary_edits"])  # type: ignore[arg-type]
    edits[-1] = edits[0]
    correction["official_end_boundary_edits"] = edits
    with pytest.raises(ValueError, match="duplicated"):
        corrected_members(source, correction)


def test_missing_entire_member_day_is_counted() -> None:
    expected = pd.MultiIndex.from_tuples(
        [("sh600001", date(2020, 1, 2)), ("sh600001", date(2020, 1, 3))],
        names=["instrument", "datetime"],
    )
    present = expected[:1]
    frame = pd.DataFrame({"F0": np.asarray([1.0])}, index=present)
    projected, counts = _project_features(frame, expected, ("F0",))
    assert len(projected) == 1
    assert counts.member_signal_rows == 2
    assert counts.missing_source_rows == 1
    assert counts.incomplete_feature_rows == 1


def test_labels_on_feature_incomplete_member_rows_are_filtered_not_scope_errors() -> None:
    allowed = pd.MultiIndex.from_tuples(
        [("sh600001", date(2020, 1, 2)), ("sh600001", date(2020, 1, 3))],
        names=["instrument", "datetime"],
    )
    frame = pd.DataFrame({"LABEL_T2_OVER_T1": [0.1, 0.2]}, index=allowed)
    complete_feature_keys = pd.DataFrame({"session": [date(2020, 1, 2)], "symbol": ["sh600001"]})
    projected = _project_labels(frame, complete_feature_keys, allowed)
    assert projected.to_dict("records") == [
        {
            "session": date(2020, 1, 2),
            "symbol": "sh600001",
            "LABEL_T2_OVER_T1": 0.1,
        }
    ]


@pytest.mark.parametrize("name", ["../escape.parquet", "a" * 64 + "/tail", "csi500"])
def test_content_child_rejects_path_escape(tmp_path: Path, name: str) -> None:
    with pytest.raises(ValueError, match="content-addressed"):
        _child(tmp_path, name)


def test_tracked_dev001_configs_parse_and_bind_fixed_label() -> None:
    root = Path(__file__).parents[1]
    use = yaml.safe_load(
        (root / "configs/v2/development/dev_001_real_v1.yaml").read_text(encoding="utf-8")
    )
    models = yaml.safe_load(
        (root / "configs/v2/models/dev_001_models_v1.yaml").read_text(encoding="utf-8")
    )
    assert use["approval_status"] == "APPROVED_FOR_THIS_EXACT_DEV_RUN"
    assert use["label"]["formula"] == "close[T+2] / close[T+1] - 1"
    assert models["models"]["lightgbm"]["n_estimators"] == 200
    assert models["parameter_search"] is False
