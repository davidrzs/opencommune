"""Public document routes do not necessarily end in a filename."""

import pytest

from opencommune.crawl.linked_archive import LinkedSource, documents


@pytest.mark.parametrize(
    "path",
    [
        "/download_file/view/123/348",
        "/download_file/view/123",
        "/sitzung?file=files%2Farchiv%2Fbudget.pdf&cid=42",
        "/dynasite.cfm?cmd=cdownload_download_download_download&id=136&bereich=506151&skipfurl=1",
    ],
)
def test_technical_download_routes_without_title_keywords(path):
    source = LinkedSource(
        bfs_id=1,
        website="https://example.test",
        vendor="custom",
        listing_urls=["https://example.test/docs"],
    )
    url = "https://example.test" + path
    assert documents(f'<a href="{url}">2025</a>', source.listing_urls[0], source) == {
        url: source.listing_urls[0]
    }


@pytest.mark.parametrize(
    "url",
    [
        "https://other.test/download_file/view/123/348",
        "https://example.test/download_file/view/not-an-id",
        "https://example.test/sitzung?file=budget.docx",
        "https://example.test/sitzung?file=a.pdf&file=b.docx",
        "https://other.test/dynasite.cfm?cmd=cdownload_download_download_download&id=136",
        "https://example.test/dynasite.cfm?cmd=delete&id=136",
        "https://example.test/dynasite.cfm?cmd=cdownload_download_download_download&id=word",
        "https://example.test/dynasite.cfm?cmd=cdownload_download_download_download&id=1&id=2",
        "https://example.test/dynasite.cfm?cmd=cdownload_download_download_download&cmd=delete&id=1",
        "https://example.test/other.cfm?cmd=cdownload_download_download_download&id=1",
    ],
)
def test_routes_keep_scope_and_file_type_boundaries(url):
    source = LinkedSource(
        bfs_id=1,
        website="https://example.test",
        vendor="custom",
        listing_urls=["https://example.test/docs"],
    )
    assert documents(f'<a href="{url}">Budget</a>', source.listing_urls[0], source) == {}
