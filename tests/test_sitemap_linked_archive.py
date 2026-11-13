"""The linked archive follows reviewed sitemap XML into municipal PDF detail pages."""

import json

import httpx
import pytest

from opencommune.config import settings
from opencommune.crawl import discovery, http, linked_archive, store
from opencommune.register import RegisterEntry

HOST = "https://commune.test"
ROOT = HOST + "/sitemap.xml"
CHILD = HOST + "/sitemap/fr_1.xml"
DETAIL = HOST + "/officielle/autorites/documents/budget-2026-123"
PDF = HOST + "/media/document/0/budget-2026.pdf?nohash"
CANONICAL_PDF = PDF + "="


def source():
    return linked_archive.LinkedSource(
        bfs_id=1,
        website=HOST,
        vendor="iomedia-nuxt",
        listing_urls=[ROOT],
        crawl_prefixes=[
            HOST + "/sitemap/",
            HOST + "/officielle/autorites/documents/",
        ],
    )


@pytest.fixture
def site(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    settings.ensure_dirs()
    monkeypatch.setattr(http.Politeness, "wait", lambda self, url: None)
    monkeypatch.setattr(http, "ATTEMPTS", 1)
    monkeypatch.setattr(discovery, "PAGE_BATCH", 2)
    routes = {}
    calls = []

    def respond(request):
        calls.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        return routes.get(str(request.url), httpx.Response(404))

    with http.make_client(httpx.MockTransport(respond)) as client:
        entry = RegisterEntry(
            bfs_id=1, name="Commune", canton="VD", website=HOST, vendor="iomedia-nuxt"
        )
        polite = http.Politeness(client, 0, settings.ua)

        def run(**kwargs):
            return linked_archive.fetch_one(
                source(), entry, client, polite, store.load_index(), limit=1, **kwargs
            )

        yield routes, calls, run


def test_sitemap_frontier_resume_pdf_and_municipal_detail_provenance(site):
    routes, calls, run = site
    routes[ROOT] = httpx.Response(
        200,
        text=f"""<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <sitemap><loc>{CHILD}</loc></sitemap>
          <sitemap><loc>{HOST}/private/other.xml</loc></sitemap>
          <sitemap><loc>https://other.test/sitemap/fr_2.xml</loc></sitemap>
        </sitemapindex>""",
        headers={"Content-Type": "application/xml"},
    )
    routes[CHILD] = httpx.Response(
        200,
        text=f"""<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>{DETAIL}</loc></url>
          <url><loc>{HOST}/officielle/autorites/documents-elsewhere/wrong</loc></url>
          <url><loc>https://other.test/officielle/autorites/documents/wrong</loc></url>
        </urlset>""",
        headers={"Content-Type": "text/xml"},
    )
    routes[DETAIL] = httpx.Response(
        200,
        text=f'<a href="{PDF}">Budget 2026</a><a href="https://other.test/private.pdf">Other</a>',
        headers={"Content-Type": "text/html"},
    )
    # The archive normalizes a bare query flag to ``nohash=`` before download.
    routes[CANONICAL_PDF] = httpx.Response(200, content=b"%PDF-1.4\nfixture\n%%EOF")

    first = run()
    assert first["status"] == "pending"
    assert first["discovery"]["pages_this_run"] == 2
    assert first["discovery"]["unvisited"] == 1
    assert set(first["frontier"]) == {ROOT, CHILD, DETAIL}
    assert CANONICAL_PDF not in first["downloads"]

    # Refresh must finish the saved frontier before re-reading successful sitemap seeds.
    finished = run(refresh=True)
    assert finished["status"] == "complete"
    assert finished["downloads"][CANONICAL_PDF]["status"] == "held"
    assert finished["documents"][CANONICAL_PDF] == DETAIL
    assert calls.count(ROOT) == calls.count(CHILD) == calls.count(DETAIL) == 1
    assert not any("other.test" in url or "/private/other.xml" in url for url in calls)
    assert not any("documents-elsewhere" in url for url in calls)

    sidecar = json.loads(next(settings.raw_dir.glob("*.json")).read_text())
    assert sidecar["listing_url"] == DETAIL
    assert sidecar["source_url"] == CANONICAL_PDF
    assert sidecar["body"] == "unknown"
    assert source().accepts_sidecar(type("Sidecar", (), sidecar))


def test_malformed_sitemap_is_a_failed_page_not_an_empty_archive(site):
    routes, _calls, run = site
    routes[ROOT] = httpx.Response(200, text="<urlset>", headers={"Content-Type": "application/xml"})
    state = run()
    assert state["pages"][ROOT]["status"] == "failed"
    assert state["pages"][ROOT]["kind"] == "sitemap_schema"
    assert state["status"] != "complete"
