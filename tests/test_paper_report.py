"""Offline tests for the paper-account HTML report."""

from __future__ import annotations

from pathlib import Path

from quant_stack.paper_report import render_paper_report, write_paper_report


def _report() -> dict[str, object]:
    return {
        "run_id": "daily-2026-09-11",
        "account_id": "paper-main",
        "trading_date": "2026-09-11",
        "cash": "123.45",
        "cumulative_fees": "3.21",
        "strategy": {"nav": "100123.45", "total_return": "0.12", "maximum_drawdown": "-0.03"},
        "benchmark": {"nav": "100010.00", "total_return": "0.01"},
        "nav_history": [
            {"date": "2026-09-10", "strategy_nav": 100000, "benchmark_nav": 100000},
            {"date": "2026-09-11", "strategy_nav": 100123.45, "benchmark_nav": 100010},
        ],
        "positions": [{"symbol": "510300", "quantity": "10.5", "market_value": "42.0"}],
        "orders": [{"order_id": "order-1", "status": "FILLED"}],
        "fills": [{"fill_id": "fill-1", "raw_reference_price": "4.00", "fee": "1.00"}],
        "rejected_orders": [{"reason": "insufficient cash"}],
        "corporate_actions": [{"type": "cash_dividend", "amount": "1.2"}],
        "data_anomalies": [{"symbol": "510300", "message": "gap checked"}],
        "evidence": {
            "input_manifest": "manifest-1",
            "raw_data_sha256": "raw-hash",
            "corporate_action_evidence_sha256": "action-hash",
            "ledger_head_sha256": "ledger-hash",
            "code_version": "abc123",
            "config_sha256": "config-hash",
        },
    }


def test_report_is_offline_and_contains_operational_evidence() -> None:
    html = render_paper_report(_report())
    assert "<!doctype html>" in html
    assert "NO_EVIDENCE_OF_EDGE" in html
    assert "100123.45" in html
    assert "ledger-hash" in html
    assert "cash_dividend" in html
    assert "<svg" in html
    assert "cdn" not in html.lower()
    assert 'src="http' not in html.lower()


def test_report_escapes_untrusted_row_text() -> None:
    report = _report()
    report["data_anomalies"] = [{"message": "<script>alert('bad')</script>"}]
    html = render_paper_report(report)
    assert "<script>" not in html
    assert "&lt;script&gt;alert(&#x27;bad&#x27;)&lt;/script&gt;" in html


def test_report_handles_missing_optional_sections() -> None:
    html = render_paper_report({"run_id": "minimal"})
    assert "Run: <code>minimal</code>" in html
    assert html.count("None recorded.") >= 5
    assert "No NAV history supplied." in html


def test_write_report_creates_a_utf8_single_file(tmp_path: Path) -> None:
    target = tmp_path / "reports" / "daily-2026-09-11.html"
    assert write_paper_report(_report(), target) == target
    assert target.read_text(encoding="utf-8") == render_paper_report(_report())
