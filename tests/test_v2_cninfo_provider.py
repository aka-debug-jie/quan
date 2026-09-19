"""Offline completeness and immutable receipt tests for CNINFO catalogs."""

import json
from pathlib import Path
from urllib.parse import parse_qs

import pytest

import quant_stack_v2.cninfo_provider as provider


def install_pages(monkeypatch: pytest.MonkeyPatch, pages: list[dict]) -> list[int]:
    calls: list[int] = []
    monkeypatch.setattr(
        provider, "_get", lambda _: b'{"stockList":[{"code":"000009","orgId":"real-id"}]}'
    )

    def post(url: str, body: bytes) -> bytes:
        params = parse_qs(body.decode())
        assert params["stock"] == ["000009,real-id"]
        page = int(params["pageNum"][0])
        calls.append(page)
        return json.dumps(pages[page - 1]).encode()

    monkeypatch.setattr(provider, "_post", post)
    return calls


def page(identity: str, more: bool, total: int = 2) -> dict:
    return {
        "totalAnnouncement": total,
        "hasMore": more,
        "announcements": [{"secCode": "000009", "announcementId": identity}],
    }


def test_all_pages_and_repeat_receipts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install_pages(monkeypatch, [page("1", True), page("2", False)])
    first = provider.discover(tmp_path, "sz000009", "2015-01-01", "2015-08-31", allow_network=True)
    second = provider.discover(tmp_path, "sz000009", "2015-01-01", "2015-08-31", allow_network=True)
    assert calls == [1, 2, 1, 2]
    assert first == second
    assert first["pages"] == 2 and len(first["announcements"]) == 2


@pytest.mark.parametrize(
    "pages",
    [
        [page("1", True), page("1", False)],
        [page("1", False)],
        [page("1", True), page("2", False, 3)],
        [{"announcements": []}],
    ],
)
def test_incomplete_catalog_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pages: list[dict]
) -> None:
    install_pages(monkeypatch, pages)
    with pytest.raises(ValueError):
        provider.discover(tmp_path, "sz000009", "2015-01-01", "2015-08-31", allow_network=True)
    assert list((tmp_path / "cninfo_catalogs").glob("*/response.json"))
