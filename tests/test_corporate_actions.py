from pathlib import Path

from quant_stack.data.corporate_actions import load_corporate_action_ledger


def test_159919_official_action_ledger_explicitly_refuses_incomplete_qfq_promotion() -> None:
    ledger = load_corporate_action_ledger(Path("configs/corporate_actions/159919_v1.yaml"))

    assert ledger.instrument.symbol == "159919"
    assert ledger.completeness == "incomplete"
    assert ledger.events[0].effective_date.isoformat() == "2019-01-11"
    assert str(ledger.events[0].split_ratio) == "1.110680861"
