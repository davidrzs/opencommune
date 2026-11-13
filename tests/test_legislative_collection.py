"""Mendrisio-style public API frontier remains scoped and resumable."""

import json
from types import SimpleNamespace

import httpx
import pytest

from opencommune.config import settings
from opencommune.crawl import http, linked_archive, store
from opencommune.crawl.sites import legislative

MUNICIPAL = "https://municipal.test"
API = "https://legislativo.test"
SEED = API + "/api/public/legislations"


def source():
    return linked_archive.LinkedSource(
        bfs_id=1,
        website=MUNICIPAL,
        vendor="custom",
        listing_urls=[SEED],
        external_listing_prefixes=[API + "/api/public/"],
        document_url_prefixes=[API + "/api/public/messages/"],
        attribution_note="Official municipal legislative portal links this public API.",
    )


def collection(kind, page=0):
    return legislative.collection_url(API, kind, 5, page)


def page(kind, page_number, *, total_pages=1, documents=()):
    return {
        "content": [{"documents": list(documents)}] if documents else [],
        "pageNumber": page_number,
        "pageSize": 100,
        "totalPages": total_pages,
        "hasNext": page_number + 1 < total_pages,
    }


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    settings.ensure_dirs()
    monkeypatch.setattr(http.Politeness, "wait", lambda self, url: None)
    monkeypatch.setattr(http, "ATTEMPTS", 1)
    routes, calls = {}, []

    def respond(request):
        url = str(request.url)
        calls.append(url)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        return routes.get(url, httpx.Response(404))

    with http.make_client(httpx.MockTransport(respond)) as client:
        yield routes, calls, client, http.Politeness(client, 0, settings.ua)


def run(engine, *, limit=1, retry_failed=False):
    _, _, client, polite = engine
    entry = SimpleNamespace(bfs_id=1, name="Municipal", canton="TI")
    return linked_archive.fetch_one(
        source(), entry, client, polite, store.load_index(), limit=limit, retry_failed=retry_failed
    )


def test_frontier_paginates_resumes_and_keeps_api_listing_provenance(engine):
    routes, calls, _, _ = engine
    routes[SEED] = httpx.Response(200, json=[{"id": 5}])
    for kind in legislative.KINDS:
        routes[collection(kind)] = httpx.Response(200, json=page(kind, 0))
    first = API + "/api/public/messages/7/messageText"
    second = API + "/api/public/messages/7/attachments/8"
    routes[collection("messages")] = httpx.Response(
        200,
        json=page(
            "messages",
            0,
            total_pages=2,
            documents=[{"filename": "first.pdf", "endpoint": "/api/public/messages/7/messageText"}],
        ),
    )
    routes[collection("messages", 1)] = httpx.Response(
        200,
        json=page(
            "messages",
            1,
            total_pages=2,
            documents=[
                {"filename": "second.pdf", "endpoint": "/api/public/messages/7/attachments/8"}
            ],
        ),
    )
    for url in (first, second):
        routes[url] = httpx.Response(200, content=b"%PDF-1.4\n" + url.encode() + b"\n%%EOF")

    state = run(engine)
    assert state["status"] == "pending"
    assert state["documents"] == {
        first: collection("messages"),
        second: collection("messages", 1),
    }
    assert state["downloads"][first]["status"] == "held"
    assert second not in state["downloads"]
    assert state["discovery"]["unvisited"] == 0
    assert collection("messages", 1) in calls

    state = run(engine)
    assert state["status"] == "complete"
    assert state["downloads"][second]["status"] == "held"
    assert calls.count(SEED) == 1
    assert calls.count(collection("messages", 1)) == 1
    sidecars = [json.loads(path.read_text()) for path in settings.raw_dir.glob("*.json")]
    assert {s["listing_url"] for s in sidecars} == {
        collection("messages"),
        collection("messages", 1),
    }
    assert all(s["body"] == "unknown" for s in sidecars)


def test_external_redirect_cannot_leave_reviewed_api_origin(engine):
    routes, calls, _, _ = engine
    routes[SEED] = httpx.Response(
        302, headers={"location": "https://other.test/api/public/legislations"}
    )
    state = run(engine)
    assert state["pages"][SEED]["kind"] == "external"
    assert state["status"] != "complete"
    assert "https://other.test/api/public/legislations" not in calls
    assert not source().allows_listing("https://other.test/api/public/legislations")


def test_schema_failure_is_recorded_and_remains_pending(engine):
    routes, _, _, _ = engine
    routes[SEED] = httpx.Response(200, json={"unexpected": "not a legislature list"})
    state = run(engine)
    assert state["pages"][SEED]["kind"] == "api_schema"
    assert state["status"] == "pending"
    assert state["documents"] == {}


def test_robots_blocks_api_before_request(engine):
    _, calls, _, polite = engine
    polite._robots["legislativo.test"] = http.RobotsRules(
        "User-agent: *\nDisallow: /api/public/", settings.ua
    )
    state = run(engine)
    assert state["pages"][SEED]["kind"] == "robots"
    assert state["status"] == "blocked"
    assert SEED not in calls
