"""Long explicit Retry-After responses survive collector process boundaries."""

import json
from types import SimpleNamespace

import httpx
import pytest

from opencommune.config import settings
from opencommune.crawl import cooldown, http


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    settings.ensure_dirs()
    monkeypatch.setattr(http.Politeness, "wait", lambda self, url: None)
    monkeypatch.setattr(http, "ATTEMPTS", 1)


def test_long_final_429_blocks_new_client_before_robots_or_request(sandbox):
    calls = []

    def respond(request):
        url = str(request.url)
        calls.append(url)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        if request.url.host in {"cool.test", "www.cool.test"}:
            return httpx.Response(429, headers={"Retry-After": "3600"})
        return httpx.Response(200, text="other host works")

    with http.make_client(httpx.MockTransport(respond)) as client:
        first = http.Politeness(client, 0, settings.ua)
        url = "https://cool.test/first"
        assert first.allowed(url)
        with pytest.raises(http.FetchFailure, match="Retry-After 3600s") as exc:
            http._send(client, first, client.build_request("GET", url))
        assert exc.value.status == 429
        assert exc.value.retry_after == "3600"
        before = list(calls)

        second = http.Politeness(client, 0, settings.ua)
        with pytest.raises(http.FetchFailure, match="host cooldown") as exc:
            second.allowed("https://www.cool.test/next")
        assert exc.value.status == 429
        with pytest.raises(http.FetchFailure, match="host cooldown"):
            http._send(client, second, client.build_request("GET", "https://cool.test/next"))
        assert calls == before  # Includes no new robots.txt request.

        other = "https://other.test/document"
        assert second.allowed(other)
        assert http._send(client, second, client.build_request("GET", other)).status_code == 200


def test_redirect_destination_503_sets_only_destination_cooldown(sandbox):
    calls = []
    origin, target = "https://source.test/start", "https://cdn.test/file"

    def respond(request):
        url = str(request.url)
        calls.append(url)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        if url == origin:
            return httpx.Response(302, headers={"Location": target})
        if url == target:
            return httpx.Response(503, headers={"Retry-After": "3600"})
        return httpx.Response(200)

    with http.make_client(httpx.MockTransport(respond)) as client:
        polite = http.Politeness(client, 0, settings.ua)
        assert polite.allowed(origin)
        with pytest.raises(http.FetchFailure, match="Retry-After") as exc:
            http._send(client, polite, client.build_request("GET", origin))
        assert exc.value.status == 503
        assert cooldown.active(target)["status"] == 503
        assert cooldown.active(origin) is None
        before = list(calls)
        next_polite = http.Politeness(client, 0, settings.ua)
        with pytest.raises(http.FetchFailure, match="host cooldown") as exc:
            next_polite.allowed(target)
        assert exc.value.status == 503
        assert calls == before
        assert next_polite.allowed("https://source.test/other")
        before_target = calls.count(target)
        with pytest.raises(http.FetchFailure, match="host cooldown"):
            http._send(client, next_polite, client.build_request("GET", origin))
        assert calls.count(target) == before_target


def test_long_robots_retry_after_propagates_retry_epoch(sandbox):
    calls = []

    def respond(request):
        calls.append(str(request.url))
        return httpx.Response(429, headers={"Retry-After": "3600"})

    with http.make_client(httpx.MockTransport(respond)) as client:
        polite = http.Politeness(client, 0, settings.ua)
        document = "https://robots.test/file.pdf"
        with pytest.raises(http.FetchFailure, match="host cooldown") as exc:
            polite.allowed(document)
        assert exc.value.status == 429
        assert exc.value.retry_at is not None
        with pytest.raises(http.FetchFailure) as repeat:
            polite.allowed(document)
        assert repeat.value.retry_at == exc.value.retry_at
        assert calls == ["https://robots.test/robots.txt"]


def test_short_retry_after_still_retries_without_persistent_cooldown(sandbox, monkeypatch):
    monkeypatch.setattr(http, "ATTEMPTS", 2)
    monkeypatch.setattr(http, "_pause", lambda seconds: None)
    attempts = 0

    def respond(request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "1"})
        return httpx.Response(200, text="ready")

    with http.make_client(httpx.MockTransport(respond)) as client:
        polite = http.Politeness(client, 0, settings.ua)
        url = "https://short.test/document"
        assert http._send(client, polite, client.build_request("GET", url)).status_code == 200
        assert attempts == 2
        assert cooldown.active(url) is None


def test_max_expiry_wins_and_invalid_record_fails_closed(sandbox):
    url = "https://site.test/document"
    long = cooldown.record(url, 3600, 429)
    short = cooldown.record("https://www.site.test/other", 60, 503)
    assert short == long
    assert cooldown.active(url)["status"] == 429
    path = cooldown._path("site.test")
    path.write_text("{broken")
    with http.make_client(
        httpx.MockTransport(lambda request: pytest.fail("network used"))
    ) as client:
        polite = http.Politeness(client, 0, settings.ua)
        with pytest.raises(http.FetchFailure, match="cooldown state unavailable"):
            polite.allowed(url)


def test_missing_required_cooldown_field_fails_closed(sandbox):
    url = "https://site.test/document"
    state = cooldown.record(url, 3600, 429)
    del state["until_utc"]
    cooldown._path("site.test").write_text(json.dumps(state))
    with http.make_client(
        httpx.MockTransport(lambda request: pytest.fail("network used"))
    ) as client:
        polite = http.Politeness(client, 0, settings.ua)
        with pytest.raises(http.FetchFailure, match="cooldown state unavailable"):
            polite.allowed(url)


def test_impossible_cooldown_duration_is_rejected_without_record(sandbox):
    url = "https://site.test/document"
    with pytest.raises(ValueError, match="supported datetime range"):
        cooldown.record(url, 1e300, 429)
    assert cooldown.active(url) is None


def test_expired_cooldown_allows_fresh_robots_and_document_request(sandbox, monkeypatch):
    now = [1_000.0]
    monkeypatch.setattr(cooldown, "time", SimpleNamespace(time=lambda: now[0]))
    url = "https://expiry.test/document"
    cooldown.record(url, 10, 429)
    calls = []

    def respond(request):
        calls.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        return httpx.Response(200, text="ready")

    with http.make_client(httpx.MockTransport(respond)) as client:
        first = http.Politeness(client, 0, settings.ua)
        with pytest.raises(http.FetchFailure, match="host cooldown"):
            first.allowed(url)
        assert calls == []
        now[0] = 1_011.0
        second = http.Politeness(client, 0, settings.ua)
        assert second.allowed(url)
        assert http._send(client, second, client.build_request("GET", url)).status_code == 200
        assert calls == ["https://expiry.test/robots.txt", url]
