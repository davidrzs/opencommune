"""A deferred page or PDF resumes after Retry-After without a manual failed retry."""

from types import SimpleNamespace

import httpx
import pytest

from opencommune.config import settings
from opencommune.crawl import cooldown, http, linked_archive


@pytest.mark.parametrize("status", [429, 503])
@pytest.mark.parametrize("defer_page", [False, True])
def test_cooldown_stops_commune_and_resumes_after_expiry(tmp_path, monkeypatch, status, defer_page):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    settings.ensure_dirs()
    monkeypatch.setattr(http.Politeness, "wait", lambda *args: None)
    now = [1000.0]
    monkeypatch.setattr(cooldown, "time", SimpleNamespace(time=lambda: now[0]))
    host = "https://cooldown.test"
    first_url = host + ("/docs" if defer_page else "/one.pdf")
    config = linked_archive.LinkedSource(
        bfs_id=1,
        website=host,
        vendor="custom",
        listing_urls=[host + "/docs"] if defer_page else [],
        document_urls=[] if defer_page else [host + "/one.pdf", host + "/two.pdf"],
    )
    calls = []

    def respond(request):
        url = str(request.url)
        calls.append(url)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        if url == first_url and now[0] == 1000.0:
            return httpx.Response(status, headers={"Retry-After": "3600"})
        if request.url.path == "/docs":
            return httpx.Response(200, text='<a href="/one.pdf">One</a><a href="/two.pdf">Two</a>')
        return httpx.Response(200, content=b"%PDF-1.4\n" + url.encode())

    with http.make_client(httpx.MockTransport(respond)) as client:
        entry = SimpleNamespace(name="Example", canton="BE")
        index = {}

        def run():
            return linked_archive.fetch_one(
                config,
                entry,
                client,
                http.Politeness(client, 0, settings.ua),
                index,
                limit=10,
            )

        first = run()
        assert first["status"] == "blocked"
        section = "pages" if defer_page else "downloads"
        assert first[section][first_url]["retry_at"] == 4600.0
        assert host + "/two.pdf" not in calls
        before = list(calls)
        again = run()
        assert again["status"] == "blocked"
        assert calls == before  # no robots request or alternate file during host cooldown
        now[0] = 4601.0
        resumed = run()
    assert resumed["status"] == "complete"
    assert len(resumed["downloads"]) == 2
    assert all(x["status"] == "held" for x in resumed["downloads"].values())
    assert calls.count(first_url) == 2
