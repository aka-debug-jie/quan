# ruff: noqa: RUF001
"""Candidate extraction preserves original text and never invents fields."""

from quant_stack_v2.exq_corporate_action_extract import extract


def test_extract_keeps_page_and_only_explicit_date_fields() -> None:
    text = "每10股派现金2元，股权登记日：2015年6月1日，除权除息日：2015年6月2日。\f换股实施公告。"
    result = extract(text)
    assert result[0]["page"] == 1
    assert result[0]["date_fields"] == {"股权登记日": "2015年6月1日", "除权除息日": "2015年6月2日"}
    assert result[1]["date_fields"] == {}
