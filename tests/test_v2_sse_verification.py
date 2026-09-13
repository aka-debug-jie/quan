"""SSE archive verification regressions independent of the live exchange."""

import json
from dataclasses import asdict
from datetime import date
from hashlib import sha256
from pathlib import Path

import pytest

from quant_stack_v2.sse_suspension import SSEManifest
from quant_stack_v2.sse_verification import verify_batch, verify_response


def response(**changes: object) -> bytes:
    row = dict(
        productCode="600485",
        controlType="TR",
        type="LXTP",
        stopTime="",
        startStopDate="20161226",
        endStopDate="20161227",
    )
    row.update(changes)
    return json.dumps(
        dict(
            sqlId="GW_PL_JYTS_TFPXX",
            result=[row],
            pageHelp=dict(total=1, pageNo=1, pageCount=1, data=[row]),
        )
    ).encode()


@pytest.mark.parametrize("changes", [{"productCode": "600000"}, {"endStopDate": "20161225"}])
def test_bad_identity_or_dates_rejected(changes: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        verify_response(response(**changes), "sh600485")


def test_filters_and_pagination() -> None:
    assert verify_response(response(stopTime="AM"), "sh600485")[0] == []
    assert verify_response(response(controlType="CB"), "sh600485")[0] == []
    assert verify_response(response(type="LSTP", stopTime="WH"), "sh600485")[0] == [
        (date(2016, 12, 26), date(2016, 12, 27))
    ]
    value = json.loads(response())
    value["pageHelp"]["total"] = 101
    with pytest.raises(ValueError, match="pagination"):
        verify_response(json.dumps(value).encode(), "sh600485")


def test_batch_matches_real_missing_dates_and_detects_tamper(tmp_path: Path) -> None:
    def write(path: Path, value: object) -> bytes:
        body = json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        return body

    audit = tmp_path / "audit.json"
    audit_body = write(
        audit,
        {
            "issues": [
                dict(symbol="sh600485", session=d, kind="MISSING_OR_SUSPENDED_UNVERIFIED")
                for d in ("2016-12-26", "2016-12-27")
            ]
        },
    )
    task = dict(
        symbol="sh600485",
        exchange="SH",
        start_session="2016-12-26",
        end_session="2016-12-27",
        session_count=2,
    )
    body = (
        json.dumps(
            dict(audit_sha256=sha256(audit_body).hexdigest(), intervals=[task]),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        + b"\n"
    )
    plan = tmp_path / (sha256(body).hexdigest() + ".json")
    plan.write_bytes(body)
    raw = response(endStopDate="20161226")
    digest = sha256(raw).hexdigest()
    raw_path = tmp_path / "sse_suspension" / digest / "response.json"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_bytes(raw)
    manifest = SSEManifest("sh600485", "2016-12-26", "2016-12-27", digest, 1, "1.0.0")
    write(
        tmp_path / "sse_suspension_manifests" / manifest.identity_sha256 / "manifest.json",
        asdict(manifest),
    )
    batch = dict(
        plan_sha256=sha256(body).hexdigest(),
        exchange="SSE",
        task_count=1,
        manifest_sha256s=[manifest.identity_sha256],
    )
    batch_body = json.dumps(batch, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    index = tmp_path / sha256(batch_body).hexdigest() / "index.json"
    write(index, batch)
    result = verify_batch(index, plan, audit, tmp_path)
    assert result["interval_counts"]["PARTIAL"] == 1
    assert result["covered_sessions"] == 1
    assert result == verify_batch(index, plan, audit, tmp_path)
    raw_path.write_bytes(b"tampered")
    assert verify_batch(index, plan, audit, tmp_path)["interval_counts"]["CONFLICT"] == 1
