"""Final history replay retains actual evidence and interval accounting."""

from pathlib import Path
from typing import Any

import pytest
from test_v2_szse_history import fixture

from quant_stack_v2.szse_history_verification import main, verify


def test_full_replay_history_counts_and_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    history = fixture(tmp_path, monkeypatch)
    baseline: dict[str, Any] = {
        "source_missing_sessions": 3,
        "newly_explained_sessions": 0,
        "newly_explained_by_symbol": {},
        "claims": [],
        "membership_gate": "BLOCKED_DATA",
        "conflict_sessions": 0,
        "results": [
            {
                "task": {
                    "symbol": "sz000001",
                    "start_session": "2017-01-17",
                    "end_session": "2017-10-27",
                },
                "dates": [
                    {"session": d, "classification": "UNEXPLAINED", "evidence": []}
                    for d in ["2017-01-17", "2017-10-26", "2017-10-27"]
                ],
            }
        ],
    }
    monkeypatch.setattr("quant_stack_v2.szse_history_verification.supplement", lambda *a: baseline)
    result = verify(tmp_path / "unused.json", tmp_path / "unused.json", history)
    assert result["covered_sessions"] == result["history_explained_sessions"] == 2
    assert result["uncovered_sessions"] == 1
    assert result["interval_counts"] == {"FULL": 0, "PARTIAL": 1, "NO_MATCH": 0, "CONFLICT": 0}
    assert result["residual"][0]["session"] == "2017-10-27"
    assert result["membership_gate"] == result["gap_gate"] == "BLOCKED_DATA"
    assert result["newly_explained_by_symbol"] == {"sz000001": 2}


@pytest.mark.parametrize(
    ("gap_gate", "membership_gate", "expected"),
    [
        ("PASS", "PASS", 0),
        ("BLOCKED_DATA", "PASS", 1),
        ("PASS", "BLOCKED_DATA", 1),
        ("BLOCKED_DATA", "BLOCKED_DATA", 1),
    ],
)
def test_cli_requires_both_gates_to_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gap_gate: str,
    membership_gate: str,
    expected: int,
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "replay",
            "--report",
            "unused",
            "--issuer",
            "unused",
            "--history",
            "unused",
            "--output-root",
            str(tmp_path),
        ],
    )
    monkeypatch.setattr(
        "quant_stack_v2.szse_history_verification.verify",
        lambda *a: {"gap_gate": gap_gate, "membership_gate": membership_gate},
    )
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == expected
