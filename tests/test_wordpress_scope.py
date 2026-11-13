"""Reviewed WordPress file hosts do not widen the municipal API scope."""

import json

import httpx
import pytest

from opencommune.config import settings
from opencommune.crawl import http, wordpress
from opencommune.register import RegisterEntry

SITE = "https://commune.test"
API = SITE + "/wp-json/wp/v2/media"
PAGE = "/wp-json/wp/v2/media?mime_type=application%2Fpdf&per_page=100&page=1"
FILES = "https://files.test/wp-content/uploads/"
PDF = b"%PDF-1.4\npublic fixture\n%%EOF"


def source(**changes):
    return wordpress.ArchiveSourceConfig(bfs_id=1, website=SITE, listing_url=API, **changes)


def media(url, identifier):
    return {
        "id": identifier,
        "source_url": url,
        "mime_type": "application/pdf",
        "title": {"rendered": "Public document"},
    }


@pytest.fixture
def site(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    settings.ensure_dirs()
    monkeypatch.setattr(wordpress, "bfs_register", lambda: {1: ("Commune", "ZH")})
    monkeypatch.setattr(http.Politeness, "wait", lambda self, url: None)
    monkeypatch.setattr(http, "ATTEMPTS", 1)
    routes = {
        ("commune.test", "/robots.txt"): (200, "User-agent: *\nAllow: /", {}),
        ("files.test", "/robots.txt"): (200, "User-agent: *\nAllow: /", {}),
    }
    calls = []

    def respond(request):
        calls.append(str(request.url))
        status, body, headers = routes.get(
            (request.url.host, request.url.raw_path.decode()), (404, "missing", {})
        )
        return httpx.Response(status, content=body, headers=headers)

    entry = RegisterEntry(bfs_id=1, name="Commune", canton="ZH", website=SITE, vendor="wordpress")
    with http.make_client(httpx.MockTransport(respond)) as client:
        yield routes, calls, client, http.Politeness(client, 0, settings.ua), entry


@pytest.mark.parametrize(
    "prefix",
    [
        "https://files.test/",
        "https://files.test/wp-content/uploads",
        "https://files.test/wp-content/uploads/?x=1",
        "https://files.test/wp-content/uploads/#section",
        "https://files.test/wp-content/uploads/../private/",
        "https://files.test/wp-content/uploads/%2e%2e/private/",
        "ftp://files.test/wp-content/uploads/",
        "https://user@files.test/wp-content/uploads/",
    ],
)
def test_prefix_requires_safe_directory_and_attribution(prefix):
    with pytest.raises(ValueError):
        source(document_url_prefixes=[prefix], attribution_note="Reviewed")
    with pytest.raises(ValueError, match="attribution"):
        source(document_url_prefixes=[FILES], attribution_note=" ")


def test_prefix_scope_is_host_scheme_and_directory_exact():
    config = source(document_url_prefixes=[FILES], attribution_note="Municipal media host")
    assert config.allows_document(FILES + "2026/report.pdf")
    assert not config.allows_document("http://files.test/wp-content/uploads/report.pdf")
    assert not config.allows_document("https://files.test/wp-content/uploads-old/report.pdf")
    assert not config.allows_document("https://files.test.evil/wp-content/uploads/report.pdf")
    assert not config.allows_document(FILES + "../private/report.pdf")
    assert not config.allows_document(FILES + "%2e%2e/private/report.pdf")


def test_newly_allowed_api_file_and_redirect_are_retried(site):
    routes, calls, client, polite, entry = site
    direct = FILES + "direct.pdf"
    redirected = FILES + "redirected.pdf"
    original = SITE + "/attachment.pdf"
    routes[("commune.test", PAGE)] = (
        200,
        json.dumps([media(direct, 1), media(original, 2)]),
        {"X-WP-TotalPages": "1"},
    )
    routes[("commune.test", "/attachment.pdf")] = (
        302,
        b"",
        {"Location": redirected},
    )
    routes[("files.test", "/wp-content/uploads/direct.pdf")] = (200, PDF, {})
    routes[("files.test", "/wp-content/uploads/redirected.pdf")] = (200, PDF + b"2", {})
    index = {}
    initial = wordpress.fetch_one(source(), entry, client, polite, index)
    assert direct in initial["review_documents"]
    assert original in initial["review_documents"]
    assert direct not in calls and redirected not in calls

    reviewed = source(document_url_prefixes=[FILES], attribution_note="Reviewed media directory")
    final = wordpress.fetch_one(reviewed, entry, client, polite, index)
    assert final["status"] == "complete"
    assert final["review_documents"] == {}
    assert final["downloads"][direct]["status"] == "held"
    assert final["downloads"][original]["status"] == "held"
    assert calls.count(SITE + PAGE) == 2  # prior excluded API record lacked listing metadata
    assert calls.count(direct) == 1
    assert calls.count(redirected) == 1
    assert len(list(settings.raw_dir.glob("*.pdf"))) == 2


def test_reviewed_pdf_prefix_does_not_allow_api_redirect(site):
    routes, calls, client, polite, entry = site
    destination = FILES + "media"
    routes[("commune.test", PAGE)] = (302, b"", {"Location": destination})
    state = wordpress.fetch_one(
        source(document_url_prefixes=[FILES], attribution_note="Reviewed media directory"),
        entry,
        client,
        polite,
        {},
    )
    assert state["status"] == "listing_error"
    assert destination not in calls
    assert "files.test/robots.txt" not in " ".join(calls)
