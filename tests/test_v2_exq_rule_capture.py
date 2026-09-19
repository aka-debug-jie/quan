"""Offline provenance tests for EXQ official rule capture."""

from pathlib import Path

from quant_stack_v2.exq_rule_capture import capture


def test_rule_capture_archives_configured_sources(tmp_path: Path) -> None:
    source = tmp_path / "sources.yaml"
    source.write_text(
        "status: PENDING_CAPTURE_AND_DATE_BINDING\n"
        "sources:\n"
        "  - {id: t1, url: https://www.csrc.gov.cn/rule}\n",
        encoding="utf-8",
    )
    result = capture(
        source, tmp_path / "artifacts", allow_network=True, fetcher=lambda _: (b"x", {})
    )
    assert result["status"] == "OFFICIAL_SOURCE_BYTES_CAPTURED_DATE_BINDING_PENDING"
    assert len(result["sources"]) == 1
