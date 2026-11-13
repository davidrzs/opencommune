"""Discovery resumes through archive/detail pages without crossing reviewed sections."""

import html as html_module
import json
from types import SimpleNamespace

import httpx
import pytest

from opencommune.config import settings
from opencommune.crawl import discovery, http
from opencommune.crawl import linked_archive as archive

HOST = "https://example.test"


@pytest.fixture
def site(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    settings.ensure_dirs()
    monkeypatch.setattr(http.Politeness, "wait", lambda *args: None)
    monkeypatch.setattr(http, "ATTEMPTS", 1)
    routes, calls, index = {}, [], {}

    def respond(request):
        path = request.url.raw_path.decode()
        calls.append(path)
        if path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        return routes.get(path, httpx.Response(404))

    with http.make_client(httpx.MockTransport(respond)) as client:
        polite = http.Politeness(client, 0, settings.ua)

        def run(source=None, **kwargs):
            source = source or archive.LinkedSource(
                bfs_id=1,
                website=HOST,
                vendor="custom",
                listing_urls=[HOST + "/archive"],
                crawl_prefixes=[HOST + "/archive"],
            )
            return archive.fetch_one(
                source,
                SimpleNamespace(name="Example", canton="ZH"),
                client,
                polite,
                index,
                limit=kwargs.pop("limit", 1),
                **kwargs,
            )

        yield routes, calls, run


def html(body):
    return httpx.Response(200, text=body)


def pdf(value):
    return httpx.Response(200, content=b"%PDF-1.4 " + value.encode())


def test_embedded_tables_follow_reviewed_details_and_download_all_titles(site):
    routes, calls, run = site
    rows = [
        {"title": '<a href="/archive/2021">Old meeting</a>'},
        {"title": '<a href="https://other.test/archive/2021">Other commune</a>'},
        {"title": '<a href="/private/2021">Outside reviewed section</a>'},
    ]
    routes["/archive"] = html(
        '<div data-entities="' + html_module.escape(json.dumps(rows), quote=True) + '"></div>'
    )
    files = [
        {"title": '<a href="/_doc/100">Budget</a>'},
        {"title": '<a href="/other.pdf">Unclassified attachment</a>'},
    ]
    routes["/archive/2021"] = html(
        '<div data-entities="' + html_module.escape(json.dumps(files), quote=True) + '"></div>'
    )
    routes["/_doc/100"], routes["/other.pdf"] = pdf("budget"), pdf("other")
    state = run(limit=10)
    assert set(state["downloads"]) == {HOST + "/_doc/100", HOST + "/other.pdf"}
    assert set(state["pages"]) == {HOST + "/archive", HOST + "/archive/2021"}
    assert "/private/2021" not in calls
    before = calls.copy()
    assert run(limit=10)["status"] == "complete"
    assert calls == before


def test_pagination_detail_resume_independent_of_pdf_budget(site, monkeypatch):
    routes, calls, run = site
    monkeypatch.setattr(discovery, "PAGE_BATCH", 2)
    routes["/archive"] = html('<a href="/first.pdf">A</a><a href="?page=2">Next</a>')
    routes["/archive?page=2"] = html(
        '<a href="/archive/2025">Year</a><a href="/archive#top">Back</a>'
    )
    routes["/archive/2025"] = html('<a href="/second.pdf">B</a>')
    routes["/first.pdf"], routes["/second.pdf"] = pdf("first"), pdf("second")
    state = run()
    assert state["discovery"]["pages_this_run"] == 2
    assert state["discovery"]["unvisited"] == 1
    # Refresh continues unfinished work, rather than repeatedly resetting the seeds.
    state = run(refresh=True)
    assert state["status"] == "complete"
    assert calls.count("/archive") == 1
    assert calls.count("/first.pdf") == 1
    assert len(state["downloads"]) == 2
    assert state["documents"][HOST + "/second.pdf"] == HOST + "/archive/2025"


def test_scope_redirects_and_catalog_provenance(site):
    routes, calls, run = site
    routes["/archive"] = html("""<a href="/archive/child">child</a>
        <a href="/archive-other">wrong</a><a href="https://other.test/archive">external</a>
        <a href="/archive/redirect">redirect</a>""")
    routes["/archive/child"] = html('<a href="/file.pdf">PDF</a>')
    routes["/file.pdf"] = pdf("file")
    routes["/archive/redirect"] = httpx.Response(302, headers={"location": HOST + "/other"})
    state = run(limit=10)
    assert "/other" not in calls and "/archive-other" not in calls
    assert state["pages"][HOST + "/archive/redirect"]["kind"] == "external"
    assert state["status"] == "pending"
    source = archive.LinkedSource.model_validate(state["source"])
    sidecar = SimpleNamespace(
        adapter="linked_archive",
        body="unknown",
        source_url=HOST + "/file.pdf",
        listing_url=HOST + "/archive/child",
    )
    assert source.accepts_sidecar(sidecar)
    sidecar.listing_url = HOST + "/other"
    assert not source.accepts_sidecar(sidecar)


def test_checkpoint_upgrade_discovers_old_successful_seed(site):
    routes, calls, run = site
    old = archive.LinkedSource(
        bfs_id=1, website=HOST, vendor="custom", listing_urls=[HOST + "/archive"]
    )
    routes["/archive"] = html('<a href="/archive/child">child</a>')
    routes["/archive/child"] = html('<a href="/file.pdf">file</a>')
    routes["/file.pdf"] = pdf("file")
    run(old)
    state = run(old.model_copy(update={"crawl_prefixes": [HOST + "/archive"]}))
    assert state["downloads"][HOST + "/file.pdf"]["status"] == "held"
    assert calls.count("/archive") == 2


@pytest.mark.parametrize("kind", ["depth", "capacity"])
def test_limits_never_claim_complete(site, monkeypatch, kind):
    routes, _, run = site
    monkeypatch.setattr(
        discovery, "MAX_DEPTH" if kind == "depth" else "MAX_PAGES", 0 if kind == "depth" else 1
    )
    routes["/archive"] = html('<a href="/archive/child">child</a>')
    state = run()
    assert state["status"] == "pending"
    assert state["discovery"][kind + "_limited"] == 1


def test_robots_block_child_and_oversized_html(site, monkeypatch):
    routes, _calls, run = site
    routes["/archive"] = html('<a href="/archive/child">child</a>')
    routes["/archive/child"] = httpx.Response(429)
    state = run()
    assert state["status"] == "blocked"
    assert state["discovery"]["failed"] == 1
    monkeypatch.setattr(discovery, "MAX_HTML_BYTES", 4)
    state = run(refresh=True, retry_failed=True)
    assert state["pages"][HOST + "/archive"]["kind"] == "html_size"


def test_prefix_validation_and_query_normalization():
    for prefix in [
        HOST + "/",
        "https://other.test/archive",
        HOST + "/archive?all=1",
        HOST + "/archive/../other",
    ]:
        with pytest.raises(ValueError):
            archive.LinkedSource(
                bfs_id=1,
                website=HOST,
                vendor="custom",
                listing_urls=[HOST + "/archive"],
                crawl_prefixes=[prefix],
            )
    assert discovery.page_url(HOST + "/archive?z=2&a=1#top") == HOST + "/archive?a=1&z=2"
    assert (
        discovery.page_url(HOST + "/archive?csrf=abc&Page_0=2&csrf_token=def&csrf=xyz")
        == HOST + "/archive?Page_0=2"
    )
    assert discovery.page_url(HOST + "/index.php?apid=123&apdo=login") is None
    assert discovery.page_url(HOST + "/index.php?apid=123&apdo=detail") == (
        HOST + "/index.php?apdo=detail&apid=123"
    )
    assert not discovery.within(HOST + "/archive%2f..%2fprivate", HOST + "/archive")


def test_large_opaque_pdf_does_not_hit_html_limit(site, monkeypatch):
    routes, _, run = site
    monkeypatch.setattr(discovery, "MAX_HTML_BYTES", 100)
    routes["/archive"] = html('<a href="/archive/download">File</a>')
    routes["/archive/download"] = pdf("x" * 1000)
    state = run()
    assert state["downloads"][HOST + "/archive/download"]["status"] == "held"
    assert state["status"] == "complete"


def test_new_seed_promotes_previously_depth_limited_page(site, monkeypatch):
    routes, _, run = site
    monkeypatch.setattr(discovery, "MAX_DEPTH", 1)
    routes["/archive"] = html('<a href="/archive/year">Year</a>')
    routes["/archive/year"] = html('<a href="/archive/year/meeting">Meeting</a>')
    routes["/archive/year/meeting"] = html('<a href="/file.pdf">File</a>')
    routes["/file.pdf"] = pdf("file")
    state = run()
    assert state["discovery"]["depth_limited"] == 1
    config = archive.LinkedSource.model_validate(state["source"])
    config.listing_urls.append(HOST + "/archive/year")
    state = run(config)
    assert state["frontier"][HOST + "/archive/year"]["depth"] == 0
    assert state["status"] == "complete"


def test_govis_routing_ids_keep_section_boundaries():
    prefix = HOST + "/politik/rechtssammlung.html/71"
    assert discovery.within(HOST + "/politik/rechtssammlung/grundlagen.html/228", prefix)
    assert discovery.within(HOST + "/politik/rechtssammlung.html/71?page=2", prefix)
    assert not discovery.within(HOST + "/politik/rechtssammlung-andere.html/72", prefix)


def test_robots_excluded_child_is_not_requested(site, monkeypatch):
    routes, calls, run = site
    routes["/archive"] = html('<a href="/archive/private">Private</a>')
    original = http.Politeness.allowed
    monkeypatch.setattr(
        http.Politeness,
        "allowed",
        lambda self, url: False if url.endswith("/private") else original(self, url),
    )
    state = run()
    assert state["status"] == "blocked"
    assert "/archive/private" not in calls
    assert state["pages"][HOST + "/archive/private"]["kind"] == "robots"


@pytest.mark.parametrize("size,accepted", [(2_300_000, True), (4_100_000, False)])
def test_large_archive_index_stays_bounded(site, size, accepted):
    routes, calls, run = site
    routes["/archive"] = html("<!--" + "x" * size + '--><a href="/late.pdf">document</a>')
    routes["/late.pdf"] = pdf("late")
    state = run()
    if accepted:
        assert state["downloads"][HOST + "/late.pdf"]["status"] == "held"
    else:
        assert state["pages"][HOST + "/archive"]["kind"] == "html_size"
        assert "/late.pdf" not in calls
        assert state["status"] != "complete"


def test_pagination_reaches_old_pages_without_using_navigation_depth(site):
    routes, _calls, run = site
    routes["/archive"] = html('<a href="?page=1">Next</a>')
    for n in range(1, 10):
        routes[f"/archive?page={n}"] = html(f'<a href="?page={n + 1}">Next</a>')
    routes["/archive?page=10"] = html('<a href="/old.pdf">Old document</a>')
    routes["/old.pdf"] = pdf("old")
    state = run()
    assert state["downloads"][HOST + "/old.pdf"]["status"] == "held"
    assert state["discovery"]["depth_limited"] == 0


@pytest.mark.parametrize(
    "child",
    [
        "/archive/deeper?page=2",
        "/archive?category=2",
        "/archive?page=2&category=3",
        "/archive?page=other",
    ],
)
def test_only_numeric_pagination_preserves_depth(child):
    assert discovery.child_depth(HOST + "/archive", HOST + child, 4) == 5


@pytest.mark.parametrize(
    "query",
    [
        "tx_news_pi1%5BcurrentPage%5D=7&tx_news_pi1%5Bcontroller%5D=News&cHash=" + "a" * 32,
        "tx_news_pi1%5B%40widget_0%5D%5BcurrentPage%5D=12",
        "tx_ttnews%5Bpointer%5D=9&L=0&cHash=" + "b" * 32,
    ],
)
def test_published_typo3_pagination_does_not_consume_depth(query):
    parent = HOST + "/archive" + ("?L=0" if "L=0" in query else "")
    assert discovery.child_depth(parent, HOST + "/archive?" + query, 6) == 6


@pytest.mark.parametrize(
    "query",
    [
        "tx_news_pi1%5BcurrentPage%5D=7&tx_news_pi1%5Bnews%5D=123",
        "tx_news_pi1%5BcurrentPage%5D=all",
        "tx_news_pi1%5BcurrentPage%5D=7&tx_news_pi1%5Bcontroller%5D=Other",
        "cHash=" + "a" * 32,
        "tx_ttnews%5Bpointer%5D=7&L=1",
    ],
)
def test_typo3_details_filters_and_non_numeric_pages_still_consume_depth(query):
    assert discovery.child_depth(HOST + "/archive", HOST + "/archive?" + query, 6) == 7


def test_previously_depth_limited_typo3_page_is_revisited_once(site):
    routes, calls, run = site
    source = archive.LinkedSource(
        bfs_id=1,
        website=HOST,
        vendor="typo3",
        listing_urls=[HOST + "/archive"],
        crawl_prefixes=[HOST + "/archive"],
    )
    routes["/archive"] = html("")
    state = run(source)
    state["frontier"][HOST + "/archive"]["depth"] = 6
    state["pages"][HOST + "/archive"]["depth_limited"] = 1
    state.pop("typo3_pagination_version")
    archive.save(state)
    routes["/archive"] = html('<a href="?tx_news_pi1%5BcurrentPage%5D=7">Older</a>')
    routes["/archive?tx_news_pi1%5BcurrentPage%5D=7"] = html('<a href="/old.pdf">Old budget</a>')
    routes["/old.pdf"] = pdf("old budget")
    state = run(source)
    assert state["downloads"][HOST + "/old.pdf"]["status"] == "held"
    assert state["typo3_pagination_version"] == 1
    assert calls.count("/archive") == 2
    run(source)
    assert calls.count("/archive") == 2


@pytest.mark.parametrize("content_type", ["application/json", "text/x-json;charset=UTF-8"])
def test_magnolia_json_listing_respects_article_scope(site, content_type):
    routes, calls, run = site
    api = "/municipality-ajax/bulletins?startIndex=0&maxResults=10"
    routes[api] = httpx.Response(
        200,
        headers={"content-type": content_type},
        json={
            "results": [
                {"pageURL": "/news/report.html"},
                {"pageURL": "https://outside.test/news/private.html"},
                {"pageURL": "/unreviewed/secret.html"},
            ]
        },
    )
    routes["/news/report.html"] = html('<a href="/budget.pdf">Budget</a>')
    routes["/budget.pdf"] = pdf("budget")
    source = archive.LinkedSource(
        bfs_id=1,
        website=HOST,
        vendor="custom",
        listing_urls=[HOST + api],
        crawl_prefixes=[HOST + "/municipality-ajax/bulletins", HOST + "/news"],
    )
    state = run(source)
    assert state["downloads"][HOST + "/budget.pdf"]["status"] == "held"
    assert "/unreviewed/secret.html" not in calls
    assert "/news/private.html" not in calls


def test_magnolia_legacy_mime_does_not_accept_html_or_claim_completion(site):
    routes, _calls, run = site
    api = "/municipality-ajax/bulletins?startIndex=0&maxResults=10"
    routes[api] = httpx.Response(
        200, text="<html>Server error</html>", headers={"content-type": "text/x-json"}
    )
    source = archive.LinkedSource(
        bfs_id=1, website=HOST, vendor="custom", listing_urls=[HOST + api]
    )
    state = run(source)
    assert state["pages"][HOST + api]["kind"] == "api_schema"
    assert state["status"] != "complete"
    assert not state["documents"]


@pytest.mark.parametrize("field", ["max_depth", "max_pages"])
def test_raised_limits_read_again_the_pages_they_left_out(site, monkeypatch, field):
    routes, _calls, run = site
    monkeypatch.setattr(discovery, "MAX_DEPTH" if field == "max_depth" else "MAX_PAGES", 1)
    routes["/archive"] = html('<a href="/archive/child">child</a>')
    routes["/archive/child"] = html('<a href="/archive/child/grandchild">grandchild</a>')
    routes["/archive/child/grandchild"] = html('<a href="/file.pdf">file</a>')
    routes["/file.pdf"] = pdf("file")
    source = archive.LinkedSource(
        bfs_id=1,
        website=HOST,
        vendor="custom",
        listing_urls=[HOST + "/archive"],
        crawl_prefixes=[HOST + "/archive"],
    )
    state = run(source)
    counter = {"max_depth": "depth_limited", "max_pages": "capacity_limited"}[field]
    assert state["discovery"][counter] == 1
    state = run(source.model_copy(update={field: 5}), limit=5)
    assert state["downloads"][HOST + "/file.pdf"]["status"] == "held"
    assert state["discovery"][counter] == 0
