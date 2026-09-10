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
