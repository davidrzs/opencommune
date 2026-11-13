"""Archive identities, bounded pagination and download resume, using mock HTTP only."""

import json
import time
from types import SimpleNamespace

import httpx
import pytest

from opencommune.config import settings
from opencommune.crawl import cooldown, http, store, wordpress
from opencommune.register import RegisterEntry

HOST = "https://example.test"
ENDPOINT = HOST + "/wp-json/wp/v2/media"
PAGE1 = "/wp-json/wp/v2/media?mime_type=application%2Fpdf&per_page=100&page=1"
PAGE2 = PAGE1.replace("&page=1", "&page=2")
PDF = b"%PDF-1.4\npublic archive fixture\n%%EOF"


def config(**kwargs):
    return wordpress.ArchiveSourceConfig(bfs_id=1, website=HOST, listing_url=ENDPOINT, **kwargs)


def entry(**kwargs):
    return RegisterEntry(
        bfs_id=1,
        name="Example",
        canton="ZH",
        website=HOST,
        vendor=kwargs.pop("vendor", "wordpress"),
        **kwargs,
    )


def media(url, title="Budget", **kwargs):
    return {
        "id": 1,
        "source_url": url,
        "mime_type": "application/pdf",
        "title": {"rendered": title},
        "date": "2026-09-11T12:30:00",
        **kwargs,
    }


@pytest.fixture
def site(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    settings.ensure_dirs()
    monkeypatch.setattr(wordpress, "bfs_register", lambda: {1: ("Canonical", "ZH")})
    monkeypatch.setattr(http.Politeness, "wait", lambda self, url: None)
    monkeypatch.setattr(http, "_pause", lambda seconds: None)
    routes = {"/robots.txt": (200, "User-agent: *\nAllow: /")}
    calls = []

    def respond(request):
        calls.append(str(request.url))
        status, body, *headers = routes.get(request.url.raw_path.decode(), (404, "missing"))
        return httpx.Response(status, content=body, headers=headers[0] if headers else {})

    with http.make_client(httpx.MockTransport(respond)) as client:
        yield routes, calls, client, http.Politeness(client, 0, settings.ua)


def test_bounded_fetch_downloads_before_paginating_and_resumes(site):
    routes, calls, client, polite = site
    routes[PAGE1] = (200, json.dumps([media(HOST + "/one.pdf")]), {"X-WP-TotalPages": "2"})
    routes[PAGE2] = (200, json.dumps([media(HOST + "/two.pdf")]), {"X-WP-TotalPages": "2"})
    routes["/one.pdf"] = (200, PDF)
    routes["/two.pdf"] = (200, PDF + b"2")
    index = {}
    first = wordpress.fetch_one(config(), entry(), client, polite, index, limit=1)
    assert len(first["pages"]) == 1
    assert first["pending"] == [HOST + PAGE2]
    assert HOST + PAGE2 not in calls
    second = wordpress.fetch_one(config(), entry(), client, polite, index, limit=1)
    assert len(second["pages"]) == 2
    assert len(second["downloads"]) == 2
    assert calls.count(HOST + "/one.pdf") == 1
    third = wordpress.fetch_one(config(), entry(), client, polite, index)
    assert third["status"] == "complete"
    assert calls.count(HOST + PAGE1) == 1
    for path in settings.raw_dir.glob("*.json"):
        sidecar = json.loads(path.read_text())
        assert sidecar["body"] == "unknown"
        assert sidecar["listing_date"] is None
        assert sidecar["adapter"] == "wp_media"


def test_same_page_multiple_documents_resume_without_relisting(site):
    routes, calls, client, polite = site
    routes[PAGE1] = (
        200,
        json.dumps([media(HOST + "/one.pdf"), media(HOST + "/two.pdf")]),
        {"X-WP-TotalPages": "1"},
    )
    routes["/one.pdf"] = (200, PDF)
    routes["/two.pdf"] = (200, PDF)
    index = {}
    wordpress.fetch_one(config(), entry(), client, polite, index, limit=1)
    wordpress.fetch_one(config(), entry(), client, polite, index, limit=1)
    assert calls.count(HOST + PAGE1) == 1
    assert len(list(settings.raw_dir.glob("*.pdf"))) == 1  # SHA dedup across URL aliases
    assert len(index) == 2


def test_external_links_and_redirects_are_reviewed_without_requesting_destination(site):
    routes, calls, client, polite = site
    routes[PAGE1] = (
        200,
        json.dumps([media("https://other.test/x.pdf"), media(HOST + "/redirect.pdf")]),
        {"X-WP-TotalPages": "1"},
    )
    routes["/redirect.pdf"] = (302, "", {"Location": "https://other.test/y.pdf"})
    state = wordpress.fetch_one(config(), entry(), client, polite, {})
    assert len(state["review_documents"]) == 2
    assert not any("other.test" in call for call in calls)
    assert not list(settings.raw_dir.glob("*.pdf"))


def test_robots_stops_listing_and_retains_pending(site):
    routes, calls, client, polite = site
    routes["/robots.txt"] = (200, "User-agent: *\nDisallow: /wp-json/")
    state = wordpress.fetch_one(config(), entry(), client, polite, {})
    assert state["status"] == "listing_error"
    assert state["pending"] == [HOST + PAGE1]
    assert calls == [HOST + "/robots.txt"]


def test_identity_mismatch_never_requests(site, monkeypatch):
    _, calls, client, polite = site
    monkeypatch.setattr(wordpress, "bfs_register", lambda: {1: ("Example", "BE")})
    state = wordpress.fetch_one(config(), entry(), client, polite, {})
    assert state["status"] == "review"
    assert not calls


def test_invalid_json_keeps_listing_retryable(site):
    routes, calls, client, polite = site
    routes[PAGE1] = (200, '{"error":"no media"}')
    first = wordpress.fetch_one(config(), entry(), client, polite, {})
    assert first["status"] == "listing_error"
    routes[PAGE1] = (200, "[]", {"X-WP-TotalPages": "0"})
    second = wordpress.fetch_one(config(), entry(), client, polite, {})
    assert second["status"] == "complete"
    assert calls.count(HOST + PAGE1) == 2


def test_deadline_does_no_requests(site):
    _, calls, client, polite = site
    state = wordpress.fetch_one(config(), entry(), client, polite, {}, deadline=0)
    assert state["pending"]
    assert not calls


def test_refresh_preserves_downloads(site):
    routes, calls, client, polite = site
    routes[PAGE1] = (200, json.dumps([media(HOST + "/one.pdf")]), {"X-WP-TotalPages": "1"})
    routes["/one.pdf"] = (200, PDF)
    index = {}
    wordpress.fetch_one(config(), entry(), client, polite, index)
    wordpress.fetch_one(config(), entry(), client, polite, index, refresh=True)
    assert calls.count(HOST + PAGE1) == 2
    assert calls.count(HOST + "/one.pdf") == 1


def test_config_rejects_external_endpoint_and_duplicate_ids(tmp_path):
    with pytest.raises(ValueError):
        wordpress.ArchiveSourceConfig(
            bfs_id=1, website=HOST, listing_url="https://other.test/wp-json/wp/v2/media"
        )
    path = tmp_path / "sources.yaml"
    path.write_text(json.dumps([config().model_dump(), config().model_dump()]))
    with pytest.raises(ValueError, match="duplicate"):
        wordpress.load_sources(path)


def test_queue_lock_prevents_overlapping_wordpress_jobs(site):
    with (
        wordpress.locked(),
        pytest.raises(ValueError, match="another WordPress"),
        wordpress.locked(),
    ):
        pass


def test_source_validation_rejects_registry_mismatch_without_network(site):
    assert wordpress.validate_sources([config()], [entry()]) == [config()]
    with pytest.raises(ValueError, match="mismatch"):
        wordpress.validate_sources([config()], [entry(vendor="i-web")])
    with pytest.raises(ValueError, match="duplicate"):
        wordpress.validate_sources([config(), config()], [entry()])


def test_failed_download_is_not_retried_per_page_or_without_explicit_retry(site):
    routes, calls, client, polite = site
    routes[PAGE1] = (200, json.dumps([media(HOST + "/bad.pdf")]), {"X-WP-TotalPages": "2"})
    routes[PAGE2] = (200, "[]", {"X-WP-TotalPages": "2"})
    routes["/bad.pdf"] = (200, b"not a pdf")
    index = {}
    first = wordpress.fetch_one(config(), entry(), client, polite, index, retry_failed=True)
    assert first["downloads"][HOST + "/bad.pdf"]["status"] == "not_pdf"
    assert first["status"] == "pending"
    assert calls.count(HOST + "/bad.pdf") == 1
    still_failed = wordpress.fetch_one(config(), entry(), client, polite, index)
    assert still_failed["status"] == "pending"
    assert calls.count(HOST + "/bad.pdf") == 1
    routes["/bad.pdf"] = (200, PDF)
    final = wordpress.fetch_one(config(), entry(), client, polite, index, retry_failed=True)
    assert final["downloads"][HOST + "/bad.pdf"]["status"] == "held"
    assert final["status"] == "complete"


def test_document_rate_limit_stops_before_next_file_or_page(site):
    routes, calls, client, polite = site
    routes[PAGE1] = (
        200,
        json.dumps([media(HOST + "/limited.pdf"), media(HOST + "/other.pdf")]),
        {"X-WP-TotalPages": "2"},
    )
    routes["/limited.pdf"] = (429, "slow down", {"Retry-After": "3600"})
    state = wordpress.fetch_one(config(), entry(), client, polite, {})
    assert state["downloads"][HOST + "/limited.pdf"]["status"] == "failed"
    assert HOST + "/other.pdf" not in calls
    assert HOST + PAGE2 not in calls


@pytest.mark.parametrize("status", [429, 503])
def test_long_retry_after_download_resumes_after_expiry_without_retry_failed(
    site, monkeypatch, status
):
    routes, calls, client, polite = site
    now = [time.time()]
    clock = SimpleNamespace(time=lambda: now[0], monotonic=time.monotonic)
    monkeypatch.setattr(cooldown, "time", clock)
    monkeypatch.setattr(wordpress, "time", clock)
    routes[PAGE1] = (200, json.dumps([media(HOST + "/limited.pdf")]), {"X-WP-TotalPages": "1"})
    routes["/limited.pdf"] = (status, "slow down", {"Retry-After": "3600"})
    index = {}
    first = wordpress.fetch_one(config(), entry(), client, polite, index)
    retry_at = first["downloads"][HOST + "/limited.pdf"]["retry_at"]
    assert retry_at > now[0]
    assert calls.count(HOST + "/limited.pdf") == 1

    routes["/limited.pdf"] = (200, PDF)
    waiting = wordpress.fetch_one(config(), entry(), client, polite, index)
    assert waiting["status"] == "pending"
    assert calls.count(HOST + "/limited.pdf") == 1

    now[0] = retry_at + 1
    final = wordpress.fetch_one(config(), entry(), client, polite, index)
    assert final["downloads"][HOST + "/limited.pdf"]["status"] == "held"
    assert final["status"] == "complete"
    assert calls.count(HOST + "/limited.pdf") == 2


def test_bounded_next_pass_reaches_untouched_commune_first(site, monkeypatch):
    from contextlib import nullcontext

    _, _, client, _ = site
    first = config()
    second = first.model_copy(update={"bfs_id": 2})
    wordpress.save({"bfs_id": 1, "downloads": {"known": {"status": "held"}}})
    monkeypatch.setattr(wordpress, "validate_sources", lambda sources, entries: sources)
    monkeypatch.setattr(http, "make_client", lambda: nullcontext(client))
    monkeypatch.setattr(store, "load_index", lambda: {})
    calls = []

    def fetch_one(source, *args, **kwargs):
        calls.append(source.bfs_id)
        return {"bfs_id": source.bfs_id}

    monkeypatch.setattr(wordpress, "fetch_one", fetch_one)
    monkeypatch.setattr(wordpress, "summary", lambda state: state)
    ticks = iter([0, 0, 61])
    monkeypatch.setattr(wordpress.time, "monotonic", lambda: next(ticks, 61))
    wordpress.run_fetch(
        [first, second],
        entries=[entry(), entry().model_copy(update={"bfs_id": 2})],
        max_minutes=1,
        emit=lambda _: None,
    )
    assert calls == [2]


def test_restricted_record_does_not_discard_public_media_or_stop_pagination(site):
    routes, calls, client, polite = site
    routes[PAGE1] = (
        200,
        json.dumps(
            [
                media(HOST + "/one.pdf"),
                {"code": "rest_unauthorized", "_links": {"self": [{"href": HOST + "/private"}]}},
                media(HOST + "/two.pdf"),
            ]
        ),
        {"X-WP-TotalPages": "2"},
    )
    routes[PAGE2] = (200, json.dumps([media(HOST + "/three.pdf")]), {"X-WP-TotalPages": "2"})
    for path in ["/one.pdf", "/two.pdf", "/three.pdf"]:
        routes[path] = (200, PDF)
    state = wordpress.fetch_one(config(), entry(), client, polite, {})
    assert len(state["downloads"]) == 3
    assert state["pending"] == []
    assert state["review_items"][HOST + PAGE1] == [{"position": 1, "reason": "rest_unauthorized"}]
    assert wordpress.summary(state)["review_items"] == 1
    assert HOST + "/private" not in calls


def test_cli_validates_only_the_selected_sources(monkeypatch):
    from typer.testing import CliRunner

    from opencommune.cli import app

    good, stale = config(), config().model_copy(update={"bfs_id": 9999})
    monkeypatch.setattr(wordpress, "load_sources", lambda: [good, stale])
    seen = []

    def validate(sources, entries=None):
        if any(s.bfs_id == 9999 for s in sources):
            raise ValueError("9999: registry or website mismatch; review required")
        seen.extend(sources)
        return sources

    monkeypatch.setattr(wordpress, "validate_sources", validate)
    res = CliRunner().invoke(app, ["wordpress", "check", "--commune", str(good.bfs_id)])
    assert res.exit_code == 0 and seen == [good]
    assert CliRunner().invoke(app, ["wordpress", "check"]).exit_code != 0
