import json
from datetime import UTC, date, datetime
from hashlib import sha256

import pytest

from quant_stack.data.sse_fund_inventory import (
    SSEFundInventoryError,
    SSEFundInventoryPayload,
    load_relevant_sse_fund_announcements,
    persist_sse_fund_inventory,
)


def _payload(total: int = 2) -> SSEFundInventoryPayload:
    body = {
        "pageHelp": {"total": total},
        "result": [
            {
                "SECURITY_CODE": "510500",
                "SSEDATE": "2024-05-10",
                "TITLE": "中证500交易型开放式指数证券投资基金分红公告",
                "URL": "/action.pdf",
            },
            {
                "SECURITY_CODE": "510500",
                "SSEDATE": "2024-04-22",
                "TITLE": "中证500交易型开放式指数证券投资基金季度报告",
                "URL": "/report.pdf",
            },
        ],
    }
    return SSEFundInventoryPayload(
        symbol="510500",
        start_date=date(2015, 1, 1),
        end_date=date(2024, 5, 10),
        source_url="https://query.sse.com.cn/commonQuery.do",
        request_parameters={},
        http_metadata={":status": "200"},
        retrieved_at=datetime(2024, 5, 11, tzinfo=UTC),
        raw_bytes=json.dumps(body, separators=(",", ":")).encode(),
    )


def test_persists_complete_official_inventory_and_filters_action_rows(tmp_path) -> None:
    path = persist_sse_fund_inventory(_payload(), tmp_path)

    receipt = path.with_name("receipt.json")
    rows = load_relevant_sse_fund_announcements(
        path.parent.name,
        sha256(receipt.read_bytes()).hexdigest(),
        "510500",
        date(2015, 1, 1),
        date(2024, 5, 10),
        tmp_path,
    )

    assert path.read_bytes() == _payload().raw_bytes
    assert len(rows) == 1
    assert rows[0].url == "https://www.sse.com.cn/action.pdf"


def test_rejects_a_truncated_official_inventory_page(tmp_path) -> None:
    with pytest.raises(SSEFundInventoryError, match="not a complete page"):
        persist_sse_fund_inventory(_payload(total=3), tmp_path)


def test_rejects_an_inventory_receipt_that_does_not_cover_research_start(tmp_path) -> None:
    path = persist_sse_fund_inventory(_payload(), tmp_path)
    receipt = path.with_name("receipt.json")

    with pytest.raises(SSEFundInventoryError, match="does not cover"):
        load_relevant_sse_fund_announcements(
            path.parent.name,
            sha256(receipt.read_bytes()).hexdigest(),
            "510500",
            date(2014, 1, 1),
            date(2024, 5, 10),
            tmp_path,
        )
