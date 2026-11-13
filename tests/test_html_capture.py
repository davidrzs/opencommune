"""Decision pages published only as HTML, against saved Thörigen pages served by
httpx.MockTransport: discovery, storage by sha with content_sha256, the churn rule, the HTML checks
and the content text."""

from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from opencommune import catalog
from opencommune.config import settings
from opencommune.crawl import fetch, html_document, http, store
from opencommune.schemas import (
    AdapterConfig,
    AdapterStep,
    CommuneConfig,
    DocumentLink,
    RawSidecar,
)

FIXTURES = Path(__file__).parent / "fixtures" / "html_pages" / "thoerigen"
HOST = "https://www.thoerigen.ch"
LISTING_URL = f"{HOST}/aktuelles-liste.html"
PAGE_URL = f"{HOST}/aktuelles-info/beschluesse-des-gemeinderates-vom-17-09-2026.html"
LISTING = (FIXTURES / "listing.html").read_bytes()
PAGE = (FIXTURES / "decision.html").read_bytes()
HTML = {"content-type": "text/html; charset=utf-8"}
PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n"


def step(selector: str = "div.mod_newsreader", **kw) -> AdapterStep:
    return AdapterStep(
        selector="a[href*='aktuelles-info/']",
        text_regex="Beschlüsse des Gemeinderates",
        capture="html",
        content_selector=selector,
        **kw,
    )


def commune(max_documents: int = 1, **kw) -> CommuneConfig:
    return CommuneConfig(
        bfs_id=989,
        name="Thörigen",
        canton="BE",
        language="de",
        website=HOST,
        body="executive",
        listing_urls=[LISTING_URL],
        adapter_config=AdapterConfig(steps=[step(**kw)], max_documents=max_documents),
    )


class Site:
    """Routes keyed by URL path to a response factory; every request is kept."""

    def __init__(self) -> None:
        self.routes: dict[str, object] = {}
        self.calls: list[httpx.Request] = []
        self.add(f"{HOST}/robots.txt", b"User-agent: *\nAllow: /\n", {"content-type": "text/plain"})
        self.add(LISTING_URL, LISTING, HTML)

    def add(self, url: str, body: bytes, headers: dict, status: int = 200) -> None:
        self.routes[httpx.URL(url).path] = lambda request: httpx.Response(
            status, content=body, headers=headers
        )

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        route = self.routes.get(request.url.path)
        return route(request) if route else httpx.Response(404, content=b"not found")

    def calls_to(self, url: str) -> list[httpx.Request]:
        return [r for r in self.calls if r.url.path == httpx.URL(url).path]

    def run(self, config: CommuneConfig) -> fetch.SourceRun:
        [result] = fetch.run([config], transport=httpx.MockTransport(self.handler))
        [run] = result.runs
        return run


@pytest.fixture
def site(tmp_path, monkeypatch) -> Site:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "request_delay_seconds", 0.0)
    settings.ensure_dirs()
    monkeypatch.setattr(http, "_pause", lambda seconds: None)
    monkeypatch.setattr(http.Politeness, "_network", lambda self, host: host)
    http.Politeness._network_last.clear()
    return Site()


def raw_files(suffix: str) -> list[Path]:
    return sorted(settings.raw_dir.glob(f"*{suffix}"))


def test_step_needs_a_content_selector_for_html_and_only_on_the_last_step():
    with pytest.raises(ValidationError, match="content_selector"):
        AdapterStep(selector="a", capture="html")
    with pytest.raises(ValidationError, match="only with capture: html"):
        AdapterStep(selector="a", content_selector="main")
    with pytest.raises(ValidationError, match="last step"):
        AdapterConfig(steps=[step(), AdapterStep(selector="a")])
    with pytest.raises(ValidationError):
        AdapterStep(selector="a", capture="docx")
    assert AdapterStep(selector="a").capture == "pdf"


def test_listing_yields_the_council_decision_pages(site):
    client = http.make_client(httpx.MockTransport(site.handler))
    polite = http.Politeness(client, 0.0, settings.ua)
    found = fetch.discover(commune(max_documents=10), client, polite)
    assert found.errors == [] and found.listing == "ok"
    assert [(d.url, d.date) for d in found.listed] == [
        (PAGE_URL, dt.date(2026, 9, 17)),
        (
            f"{HOST}/aktuelles-info/beschluesse-des-gemeinderates-vom-25-08-2026.html",
            dt.date(2026, 8, 25),
        ),
        (f"{HOST}/aktuelles-info/gr-beschluesse-vom-11-08-2026.html", dt.date(2026, 8, 11)),
    ]
    assert found.listed[0].title == "Beschlüsse des Gemeinderates vom 17.09.2026"


def test_page_is_stored_by_the_sha_of_its_bytes_with_a_sidecar(site):
    site.add(PAGE_URL, PAGE, {**HTML, "etag": '"v1"'})
    run = site.run(commune())
    sha = hashlib.sha256(PAGE).hexdigest()
    assert run.errors == [] and run.downloaded == [sha]
    assert [p.name for p in raw_files(".html")] == [f"{sha}.html"]
    assert raw_files(".pdf") == [] and raw_files(".part") == []
    assert (settings.raw_dir / f"{sha}.html").read_bytes() == PAGE
    sc = RawSidecar.model_validate_json((settings.raw_dir / f"{sha}.json").read_text())
    assert sc.sha256 == sha and sc.source_url == PAGE_URL and sc.listing_url == LISTING_URL
    assert sc.content_type == "text/html; charset=utf-8" and sc.size == len(PAGE)
    assert sc.listing_date == dt.date(2026, 9, 17) and sc.body == "executive"
    assert sc.content_selector == "div.mod_newsreader"
    soup = html_document.page_soup(PAGE, sc.content_type)
    expected = html_document.content_sha256(soup.select("div.mod_newsreader"))
    assert sc.content_sha256 == expected
    entry = store.load_index()[store.canonical_url(PAGE_URL)]
    assert entry["sha256"] == sha and entry["content_sha256"] == expected
    assert catalog.html_documents() == 1


def test_changed_menu_bytes_with_the_same_decisions_store_nothing(site):
    site.add(PAGE_URL, PAGE, {**HTML, "etag": '"v1"'})
    site.run(commune())
    churned = PAGE.replace("Navigation überspringen".encode(), b"Zum Inhalt springen")
    assert churned != PAGE
    site.add(PAGE_URL, churned, {**HTML, "etag": '"v2"'})
    run = site.run(commune())
    assert run.errors == [] and run.downloaded == [] and run.skipped == [PAGE_URL]
    assert len(raw_files(".html")) == 1 and len(raw_files(".json")) == 1
    # the known page is asked for conditionally
    assert site.calls_to(PAGE_URL)[-1].headers["if-none-match"] == '"v1"'


def test_not_modified_page_stores_nothing(site):
    site.add(PAGE_URL, PAGE, {**HTML, "etag": '"v1"'})
    site.run(commune())
    site.add(PAGE_URL, b"", {}, status=304)
    run = site.run(commune())
    assert run.errors == [] and run.downloaded == [] and len(raw_files(".html")) == 1


def test_changed_decisions_are_stored_as_a_new_document(site):
    site.add(PAGE_URL, PAGE, HTML)
    first = site.run(commune()).downloaded
    amended = PAGE.replace(b"das Budget 2027", b"das Budget 2027 (korrigiert)")
    site.add(PAGE_URL, amended, HTML)
    second = site.run(commune()).downloaded
    assert len(first) == len(second) == 1 and first != second
    assert len(raw_files(".html")) == 2


def test_page_without_the_content_element_is_not_stored(site):
    site.add(PAGE_URL, PAGE, HTML)
    run = site.run(commune(selector="div.mod_relaunched_layout"))
    assert run.downloaded == []
    assert [(e.kind, e.url) for e in run.errors] == [("no_content", PAGE_URL)]
    assert "matches nothing" in run.errors[0].message
    assert list(settings.raw_dir.glob("*.html*")) == [] and raw_files(".json") == []
    assert store.canonical_url(PAGE_URL) not in store.load_index()


@pytest.mark.parametrize(
    "body, headers",
    [
        (PDF, {"content-type": "application/pdf"}),
        (b'{"a": 1}', {"content-type": "application/json"}),
        (PAGE, {}),
    ],
)
def test_non_html_response_is_rejected(site, body, headers):
    site.add(PAGE_URL, body, headers)
    run = site.run(commune())
    assert run.downloaded == [] and [e.kind for e in run.errors] == ["not_html"]
    assert [p.name for p in settings.raw_dir.iterdir() if p.name != store.INDEX_FILE] == []


def test_page_over_the_size_cap_is_rejected(site, monkeypatch):
    monkeypatch.setattr(store, "MAX_HTML_BYTES", 1000)
    site.add(PAGE_URL, PAGE, HTML)
    run = site.run(commune())
    assert [e.kind for e in run.errors] == ["too_large"] and raw_files(".html") == []


def test_known_html_document_counts_as_held_for_the_pdf_path(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    settings.ensure_dirs()
    sha = "b" * 64
    (settings.raw_dir / f"{sha}.html").write_bytes(b"<html></html>")
    link = DocumentLink(url=PAGE_URL, listing_url=LISTING_URL, title="", body="executive")
    monkeypatch.setattr(store, "_open_document", lambda *a: pytest.fail("must not request"))
    assert store.held(sha)
    assert (
        store._download(link, None, None, None, {store.canonical_url(PAGE_URL): {"sha256": sha}})
        is None
    )
