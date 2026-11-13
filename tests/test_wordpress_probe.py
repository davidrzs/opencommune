"""Offline availability checks must not mistake arbitrary pages for a PDF archive."""

import datetime as dt
import importlib.util
import json
from pathlib import Path

import httpx
import pytest

from opencommune.config import settings
from opencommune.crawl import http
from opencommune.register import RegisterEntry

_SPEC = importlib.util.spec_from_file_location(
    "wordpress_probe_script", Path(__file__).resolve().parents[1] / "scripts/probe_wordpress.py"
)
probe_script = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(probe_script)
HOST = "https://example.test"
MEDIA = "/wp-json/wp/v2/media"


@pytest.fixture
def site(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(http.Politeness, "wait", lambda self, url: None)
    monkeypatch.setattr(http.Politeness, "_network", lambda self, host: "192.0.2")
    monkeypatch.setattr(http, "ATTEMPTS", 1)
    routes = {
        ("example.test", "/robots.txt"): (200, "User-agent: *\nAllow: /", {}),
        ("other.test", "/robots.txt"): (200, "User-agent: *\nAllow: /", {}),
    }
    calls = []
    responses = []

    def answer(request):
        calls.append(request)
        status, body, headers = routes.get((request.url.host, request.url.path), (404, "", {}))
        response = httpx.Response(status, content=body, headers=headers)
        responses.append(response)
        return response

    entry = RegisterEntry(bfs_id=1, name="Example", canton="ZH", website=HOST, vendor="wordpress")
    with http.make_client(httpx.MockTransport(answer)) as client:
        polite = http.Politeness(client, 0, settings.ua)
        yield entry, client, polite, routes, calls, responses


def run(site, body, headers=None, status=200):
    entry, client, polite, routes, _, _ = site
    routes[("example.test", MEDIA)] = (status, body, headers or {})
    return probe_script.probe(entry, client, polite)


@pytest.mark.parametrize(
    "body", ["<html>Welcome</html>", "{broken", "{}", "[1]", '[{"title":"Hello"}]']
)
def test_unrelated_or_invalid_responses_do_not_qualify(site, body):
    assert run(site, body)["status"] == "invalid_response"


def test_valid_media_retains_canonical_identity_and_total(site):
    result = run(
        site,
        json.dumps(
            [{"id": 123, "mime_type": "application/pdf", "source_url": HOST + "/budget.pdf"}]
        ),
        {"x-wp-total": "120"},
    )
    assert result["status"] == "available"
    assert (result["bfs_id"], result["name"], result["canton"], result["website"]) == (
        1,
        "Example",
        "ZH",
        HOST,
    )
    assert result["total"] == 120
    assert result["sample_urls"] == [HOST + "/budget.pdf"]
    assert dt.datetime.fromisoformat(result["checked_at"]).tzinfo is not None
    request = site[4][-1]
    assert request.url.params["mime_type"] == "application/pdf"
    assert request.url.params["per_page"] == "3"
    assert "search" not in request.url.params


def test_empty_api_is_not_available(site):
    result = run(site, "[]", {"x-wp-total": "0"})
    assert result["status"] == "empty"
    assert result["total"] == 0
    assert result["sample_urls"] == []


def test_robots_prevents_media_request(site):
    site[3][("example.test", "/robots.txt")] = (200, "User-agent: *\nDisallow: /wp-json/", {})
    assert run(site, "[]")["status"] == "robots"
    assert [r.url.path for r in site[4]] == ["/robots.txt"]


def test_rate_limit_is_recorded_without_another_media_request(site):
    result = run(site, "Slow down", {"retry-after": "3600"}, status=429)
    assert result["status"] == "http_error"
    assert result["http_status"] == 429
    assert result["retry_after"] == "3600"
    assert sum(r.url.path == MEDIA for r in site[4]) == 1
    assert site[5][-1].is_closed


def test_foreign_redirect_never_qualifies_as_communes_archive(site):
    site[3][("other.test", MEDIA)] = (
        200,
        json.dumps(
            [{"id": 1, "mime_type": "application/pdf", "source_url": "https://other.test/a.pdf"}]
        ),
        {},
    )
    result = run(site, "", {"location": "https://other.test" + MEDIA}, status=302)
    assert result["status"] == "invalid_response"
    assert result["reason"] == "external_redirect"
    assert result["sample_urls"] == []


def test_redirect_target_robots_are_checked_before_fetch(site):
    site[3][("other.test", "/robots.txt")] = (200, "User-agent: *\nDisallow: /", {})
    result = run(site, "", {"location": "https://other.test" + MEDIA}, status=302)
    assert result["status"] == "robots"
    assert not any(r.url.host == "other.test" and r.url.path == MEDIA for r in site[4])


def test_large_response_is_rejected_and_closed(site):
    result = run(site, b" " * 2_000_001)
    assert result["status"] == "invalid_response"
    assert result["reason"] == "response_too_large"
    assert site[5][-1].is_closed


@pytest.mark.parametrize(
    "url", ["https:budget.pdf", "https:///budget.pdf", "https://user:secret@example.test/a.pdf"]
)
def test_malformed_or_credential_bearing_media_url_does_not_qualify(site, url):
    result = run(site, json.dumps([{"id": 123, "mime_type": "application/pdf", "source_url": url}]))
    assert result["status"] != "available"


def test_resume_preserves_success_and_defers_live_retry_after(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    entries = [
        RegisterEntry(bfs_id=i, name=f"Example {i}", canton="ZH", website=HOST, vendor="wordpress")
        for i in range(1, 6)
    ]
    report = tmp_path / "discovery/wordpress/probe.json"
    report.parent.mkdir(parents=True)
    now = dt.datetime.now(dt.UTC)
    prior = {
        "1": {"status": "available"},
        "2": {"status": "empty"},
        "3": {"status": "http_error", "retry_after": "3600", "checked_at": now.isoformat()},
        "4": {
            "status": "http_error",
            "retry_after": "60",
            "checked_at": (now - dt.timedelta(hours=2)).isoformat(),
        },
    }
    report.write_text(json.dumps(prior))
    monkeypatch.setattr(probe_script, "load_register", lambda: entries)
    monkeypatch.setattr("sys.argv", ["probe_wordpress.py", "--retry-failed"])
    called = []

    def fake_probe(entry, client, polite):
        called.append(entry.bfs_id)
        return {"bfs_id": entry.bfs_id, "status": "empty"}

    monkeypatch.setattr(probe_script, "probe", fake_probe)
    # Even an accidental HTTP call fails locally, rather than reaching a live host.
    original_make_client = http.make_client
    monkeypatch.setattr(
        http,
        "make_client",
        lambda: original_make_client(
            httpx.MockTransport(lambda request: pytest.fail("Unexpected HTTP"))
        ),
    )
    monkeypatch.setattr(http, "ATTEMPTS", http.ATTEMPTS)
    probe_script.main()
    assert called == [4, 5]
    saved = json.loads(report.read_text())
    assert saved["1"] == prior["1"]
    assert saved["3"] == prior["3"]
    assert saved["4"]["status"] == "empty"
    assert not report.with_suffix(".tmp").exists()


@pytest.mark.parametrize("media_id", [None, "123", 0, -1, True])
def test_pdf_metadata_without_valid_wordpress_identity_does_not_qualify(site, media_id):
    item = {"mime_type": "application/pdf", "source_url": HOST + "/budget.pdf"}
    if media_id is not None:
        item["id"] = media_id
    assert run(site, json.dumps([item]))["status"] == "invalid_response"
