"""Reviewed external indexes retain municipal attribution and strict path boundaries."""

import json
from types import SimpleNamespace

import httpx
import pytest

from opencommune.config import settings
from opencommune.crawl import http, linked_archive

HOST = "https://commune.test"
INDEX = "https://legislature.test/public/archive"


def source(**kwargs):
    return linked_archive.LinkedSource(
        bfs_id=1,
        website=HOST,
        vendor="custom",
        listing_urls=[INDEX],
        external_listing_prefixes=[INDEX],
        attribution_note="Official municipal website links this public legislative archive.",
        **kwargs,
    )


@pytest.mark.parametrize("url", [INDEX, INDEX + "/years/2025", INDEX + "?page=2"])
def test_reviewed_external_index_allows_section_and_pagination(url):
    assert source().allows_listing(url)


@pytest.mark.parametrize(
    "url",
    [
        INDEX + "-private",
        INDEX + "/../private",
        INDEX + "/%2e%2e/private",
        INDEX + "/%5cprivate",
        "http://legislature.test/public/archive",
        "https://other.test/public/archive",
        "https://legislature.test/admin",
        "https://legislature.test:444/public/archive",
    ],
)
def test_external_scope_does_not_escape_reviewed_host_or_path(url):
    assert not source().allows_listing(url)


@pytest.mark.parametrize(
    "prefix,note",
    [
        ("https://legislature.test/", "Reviewed"),
        ("http://legislature.test/public", "Reviewed"),
        ("https://legislature.test/public?all=1", "Reviewed"),
        ("https://legislature.test/public#all", "Reviewed"),
        ("https://legislature.test/public/../admin", "Reviewed"),
        ("https://user:password@legislature.test/public", "Reviewed"),
        (INDEX, " "),
    ],
)
def test_external_sections_need_narrow_reviewed_https_scope(prefix, note):
    with pytest.raises(ValueError):
        linked_archive.LinkedSource(
            bfs_id=1,
            website=HOST,
            vendor="custom",
            listing_urls=[HOST],
            external_listing_prefixes=[prefix],
            attribution_note=note,
        )


def test_external_listing_is_not_implicitly_document_permission():
    config = source()
    assert config.allows_listing(INDEX + "/one.pdf")
    assert not config.allows(INDEX + "/one.pdf")


def test_added_external_index_preserves_old_download_and_pdf_provenance(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    settings.ensure_dirs()
    monkeypatch.setattr(http.Politeness, "wait", lambda *args: None)
    calls = []
    external_pdf = "https://legislature.test/files/one.pdf"
    config = linked_archive.LinkedSource(
        bfs_id=1,
        website=HOST,
        vendor="custom",
        listing_urls=[HOST + "/docs"],
    )
    extended = source(document_url_prefixes=["https://legislature.test/files/"])
    extended.listing_urls.insert(0, HOST + "/docs")

    def respond(request):
        url = str(request.url)
        calls.append(url)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        if url == HOST + "/docs":
            return httpx.Response(200, text='<a href="/local.pdf">Local</a>')
        if url == INDEX:
            return httpx.Response(
                200,
                text=(
                    f'<a href="{external_pdf}">PDF</a>'
                    '<a href="https://legislature.test/admin">Unreviewed</a>'
                    '<a href="https://other.test/public/archive">Other</a>'
                ),
            )
        return httpx.Response(200, content=b"%PDF-1.4\n" + url.encode())

    with http.make_client(httpx.MockTransport(respond)) as client:
        polite = http.Politeness(client, 0, settings.ua)
        entry = SimpleNamespace(name="Example", canton="ZH")
        index = {}
        first = linked_archive.fetch_one(config, entry, client, polite, index, limit=10)
        assert first["status"] == "complete"
        second = linked_archive.fetch_one(extended, entry, client, polite, index, limit=10)
    assert second["status"] == "complete"
    assert set(second["downloads"]) == {HOST + "/local.pdf", external_pdf}
    assert calls.count(HOST + "/local.pdf") == 1
    assert not any("/admin" in u or "other.test" in u for u in calls)
    sha = second["downloads"][external_pdf]["sha256"]
    sidecar = json.loads((settings.raw_dir / (sha + ".json")).read_text())
    assert sidecar["listing_url"] == INDEX
    assert sidecar["commune_bfs_id"] == 1
    assert extended.accepts_sidecar(SimpleNamespace(**sidecar))
