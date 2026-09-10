from pathlib import Path

from quant_stack.data.corporate_actions import load_corporate_action_ledger


def test_159919_official_action_ledger_has_complete_verified_event_chain() -> None:
    ledger = load_corporate_action_ledger(Path("configs/corporate_actions/159919_v1.yaml"))

    assert ledger.instrument.symbol == "159919"
    assert ledger.completeness == "complete"
    assert ledger.events[0].effective_date.isoformat() == "2019-01-11"
    assert str(ledger.events[0].split_ratio) == "1.110680861"
    assert ledger.events[-2].effective_date.isoformat() == "2025-03-31"
    assert str(ledger.events[-2].cash_per_unit) == "0.06610"
    assert ledger.events[-1].effective_date.isoformat() == "2025-12-08"
    assert str(ledger.events[-1].cash_per_unit) == "0.0728"
    assert ledger.events[2].verification_status == "official_evidence_chain_verified"


def test_510500_ledger_preserves_verified_split_without_claiming_completeness() -> None:
    ledger = load_corporate_action_ledger(Path("configs/corporate_actions/510500_v1.yaml"))
    assert ledger.completeness == "incomplete"
    assert ledger.events[0].effective_date.isoformat() == "2015-04-14"
    assert str(ledger.events[0].split_ratio) == "0.28032483"
    assert ledger.events[0].record_date is not None
    assert ledger.events[1].effective_date.isoformat() == "2022-08-26"
    assert str(ledger.events[1].split_ratio) == "1.14539"
    assert ledger.events[2].effective_date.isoformat() == "2024-05-17"
    assert str(ledger.events[2].cash_per_unit) == "0.087"
    assert ledger.events[3].effective_date.isoformat() == "2025-01-16"
    assert str(ledger.events[3].cash_per_unit) == "0.091"
    assert ledger.events[4].effective_date.isoformat() == "2026-01-16"
    assert str(ledger.events[4].cash_per_unit) == "0.062"


def test_510300_ledger_preserves_verified_dividend_without_claiming_completeness() -> None:
    ledger = load_corporate_action_ledger(Path("configs/corporate_actions/510300_v1.yaml"))
    assert ledger.completeness == "incomplete"
    assert ledger.events[0].verification_status == "candidate"
    assert ledger.events[0].retrospective_verification
    assert ledger.events[3].effective_date.isoformat() == "2018-01-22"
    assert str(ledger.events[3].cash_per_unit) == "0.046"
    assert ledger.events[3].verification_status == "candidate"
    assert ledger.events[4].verification_status == "official_evidence_chain_verified"
    assert ledger.events[5].effective_date.isoformat() == "2019-12-11"
    assert ledger.events[5].verification_status == "official_evidence_chain_verified"
    assert ledger.events[6].effective_date.isoformat() == "2021-01-18"
    assert str(ledger.events[6].cash_per_unit) == "0.072"
    assert ledger.events[6].payment_date is not None
    assert ledger.events[7].effective_date.isoformat() == "2022-01-19"
    assert str(ledger.events[7].cash_per_unit) == "0.075"
    assert ledger.events[8].effective_date.isoformat() == "2023-01-16"
    assert str(ledger.events[8].cash_per_unit) == "0.064"
    assert ledger.events[9].effective_date.isoformat() == "2024-01-18"
    assert str(ledger.events[9].cash_per_unit) == "0.069"
    assert ledger.events[10].effective_date.isoformat() == "2025-06-18"
    assert str(ledger.events[10].cash_per_unit) == "0.088"
    assert ledger.events[11].effective_date.isoformat() == "2026-01-19"
    assert str(ledger.events[11].cash_per_unit) == "0.123"
