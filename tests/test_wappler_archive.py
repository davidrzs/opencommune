"""Public Wappler content feeds expose document links hidden from their HTML shell."""

import json
from types import SimpleNamespace

import httpx
import pytest

from opencommune.config import settings
from opencommune.crawl import http, linked_archive, store
from opencommune.crawl.sites import wappler

HOST = "https://commune.test"
GD = HOST + "/dmxConnect/api/gd_content.php?url=reglemente-verordnungen"
ARTCMS = HOST + "/dmxConnect/api/artcms_content.php?menu_id=1022"


@pytest.mark.parametrize("url", [GD, ARTCMS])
def test_only_observed_content_endpoint_forms(url):
    assert wappler.is_content_url(url)


@pytest.mark.parametrize(
    "url",
    [
        HOST + "/dmxConnect/api/gd_news.php?url=reglemente-verordnungen",
        HOST + "/dmxConnect/api/gd_content.php?url=../admin",
        HOST + "/dmxConnect/api/gd_content.php?url=docs&url=private",
        HOST + "/dmxConnect/api/artcms_content.php?menu_id=0",
        HOST + "/dmxConnect/api/artcms_content.php?menu_id=1022&admin=1",
    ],
)
def test_unreviewed_content_endpoint_forms_rejected(url):
    assert not wappler.is_content_url(url)


def test_json_fragments_resolve_relative_files_at_municipal_root_and_keep_scope():
    source = linked_archive.LinkedSource(
        bfs_id=1, website=HOST, vendor="custom", listing_urls=[ARTCMS]
    )
    body = json.dumps(
        {
            "content": [
                {
                    "content_01": (
                        '<a href="dmxDaten/docs/budget.pdf">Budget</a>'
                        '<a href="https://other.test/x.pdf">External</a>'
                    ),
                    "content_02": '<a href="/dmxDaten/docs/minutes.pdf">Minutes</a>',
                    "ignored": '<a href="/secret.pdf">Ignored</a>',
                }
            ]
        }
    )
    assert linked_archive.documents(body, ARTCMS, source) == {
        HOST + "/dmxDaten/docs/budget.pdf": ARTCMS,
        HOST + "/dmxDaten/docs/minutes.pdf": ARTCMS,
    }


@pytest.mark.parametrize(
    "body",
    [
        "not JSON",
        "[]",
        '{"content":[]}',
        '{"content":[{"content_01":123}]}',
        '{"content":[{"other":"unrelated"}]}',
    ],
)
def test_malformed_or_unrelated_artcms_json_rejected(body):
    with pytest.raises(ValueError):
        wappler.html_document(body, ARTCMS, HOST)


def test_gd_json_requires_query_object():
    with pytest.raises(ValueError, match="query"):
        wappler.html_document('{"query":null}', GD, HOST)


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


def _run(engine, listing=GD):
    _, _, client, polite = engine
    source = linked_archive.LinkedSource(
        bfs_id=1, website=HOST, vendor="custom", listing_urls=[listing]
    )
    entry = SimpleNamespace(bfs_id=1, name="Commune", canton="BE")
    return linked_archive.fetch_one(source, entry, client, polite, store.load_index(), limit=3)


def test_engine_fetches_json_listing_and_pdf_with_technical_provenance(engine):
    routes, calls, _, _ = engine
    routes[GD] = httpx.Response(
        200,
        json={"query": {"content_01": '<a href="dmxDaten/reglement.pdf">Règlement</a>'}},
    )
    routes[HOST + "/dmxDaten/reglement.pdf"] = httpx.Response(
        200, content=b"%PDF-1.4\npublic\n%%EOF"
    )
    state = _run(engine)
    assert state["pages"][GD]["documents"] == 1
    assert state["documents"][HOST + "/dmxDaten/reglement.pdf"] == GD
    assert state["downloads"][HOST + "/dmxDaten/reglement.pdf"]["status"] == "held"
    assert HOST + "/dmxDaten/reglement.pdf" in calls


def test_engine_records_json_schema_failure_without_fetching_documents(engine):
    routes, calls, _, _ = engine
    routes[GD] = httpx.Response(200, json={"query": None})
    state = _run(engine)
    assert state["pages"][GD]["kind"] == "api_schema"
    assert state["documents"] == {}
    assert all(".pdf" not in url for url in calls)


def test_engine_respects_robots_for_declared_api(engine):
    routes, calls, _, polite = engine
    routes[GD] = httpx.Response(200, json={"query": {"content_01": '<a href="/x.pdf">x</a>'}})
    polite._robots["commune.test"] = http.RobotsRules(
        "User-agent: *\nDisallow: /dmxConnect/api/", settings.ua
    )
    state = _run(engine)
    assert state["pages"][GD]["kind"] == "robots"
    assert GD not in calls
    assert state["documents"] == {}
