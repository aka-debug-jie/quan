"""Corporate leads are never treated as accounting evidence."""

import json
from hashlib import sha256
from pathlib import Path

from quant_stack_v2.exq_corporate_action_queue import build


def test_only_relevant_title_is_a_lead(tmp_path: Path) -> None:
    source = {
        "rows": [
            {
                "symbol": "sz000001",
                "announcement_id": "1",
                "title": "权益分派实施公告",
                "official_url": "https://static.cninfo.com.cn/finalpage/x.PDF",
                "pdf_sha256": "a" * 64,
                "status": "REVIEW_REQUIRED",
            },
            {
                "symbol": "sz000002",
                "announcement_id": "2",
                "title": "停牌公告",
                "official_url": "https://static.cninfo.com.cn/finalpage/y.PDF",
                "pdf_sha256": "b" * 64,
                "status": "REVIEW_REQUIRED",
            },
        ]
    }
    body = json.dumps(source, sort_keys=True, separators=(",", ":")).encode()
    path = tmp_path / (sha256(body).hexdigest() + ".pdf-review.json")
    path.write_bytes(body)
    result = build(path)
    assert result["lead_count"] == 1
    assert result["status"] == "LEADS_ONLY_NOT_ACCOUNTING_EVIDENCE"
