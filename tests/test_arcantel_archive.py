import json

import httpx
import pytest

from opencommune.config import settings
from opencommune.crawl import http
from opencommune.crawl.linked_archive import LinkedSource, documents, within_source
from opencommune.crawl.sites import arcantel as arc

HOST = "https://municipality.test"
PAGE = HOST + "/council/sessions/2025"
LIST = "/council/Lists/sessions/2025.aspx"


def source():
    return LinkedSource(
        bfs_id=1,
        website=HOST,
        vendor="arcantel",
        listing_urls=[PAGE],
        crawl_prefixes=[HOST + "/council"],
    )


def client_for(monkeypatch, *, denied="", list_path=LIST, malformed=False):
    monkeypatch.setattr(http.Politeness, "wait", lambda *args: None)
    calls = []

    def respond(request):
        calls.append(request)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: " + denied)
        if request.url.path == "/Api/Page.svc/detail":
            assert json.loads(request.content) == {"page": "/council/sessions/2025"}
            return httpx.Response(
                200,
                json={
                    "DetailResult": {
                        "Url": "/council/sessions/2025",
                        "Content": "<table><tr><td>SharepointListe</td><td>"
                        + list_path
                        + "</td></tr></table>",
                    }
                },
            )
        if request.url.path == "/Api/Menu.svc/children":
            return httpx.Response(
                200,
                json={
                    "ChildrenResult": [
                        {"FriendlyUrl": "/council/sessions/1999", "HideInMenu": False},
                        {"FriendlyUrl": "https://elsewhere.test/docs"},
                        {"FriendlyUrl": "/council/hidden", "HideInMenu": True},
                    ]
                },
            )
        assert request.url.path == "/Api/List.svc/liste"
        assert json.loads(request.content) == {"listeurl": LIST}
        return httpx.Response(
            200,
            json={
                "ListeResult": {
                    "Data": {
                        "Data": None
                        if malformed
                        else [
                            [
                                {
                                    "Key": "contenu",
                                    "Value": '<a href="/council/report.pdf">Report</a>',
                                }
                            ]
                        ]
                    }
                }
            },
        )

    client = http.make_client(httpx.MockTransport(respond))
    return client, http.Politeness(client, 0, settings.ua), calls


def test_public_page_lists_keep_human_provenance(monkeypatch):
    client, polite, calls = client_for(monkeypatch)
    with client:
        html = arc.render(client, within_source(polite, source()), source(), PAGE)
    assert "/council/sessions/1999" in html
    assert "elsewhere.test" not in html and "/council/hidden" not in html
    assert documents(html, PAGE, source()) == {HOST + "/council/report.pdf": PAGE}
    assert [r.method for r in calls if "/Api/" in r.url.path] == ["POST", "POST", "POST"]


@pytest.mark.parametrize("denied", ["/Api/", "/council/Lists/"])
def test_api_and_list_robots_exclusions_are_respected(monkeypatch, denied):
    client, polite, calls = client_for(monkeypatch, denied=denied)
    with client, pytest.raises(http.FetchFailure):
        arc.render(client, within_source(polite, source()), source(), PAGE)
    assert not any(r.url.path == "/Api/List.svc/liste" for r in calls)
    if denied == "/Api/":
        assert not any("/Api/" in r.url.path for r in calls)


@pytest.mark.parametrize(
    "path", ["//elsewhere.test/list.aspx", "/unreviewed/list.aspx", "/council/../private/list.aspx"]
)
def test_embedded_lists_cannot_expand_reviewed_scope(monkeypatch, path):
    client, polite, calls = client_for(monkeypatch, list_path=path)
    with client, pytest.raises(http.FetchFailure):
        arc.render(client, within_source(polite, source()), source(), PAGE)
    assert not any(r.url.path == "/Api/List.svc/liste" for r in calls)


def test_schema_error_does_not_claim_success(monkeypatch):
    client, polite, _ = client_for(monkeypatch, malformed=True)
    with client, pytest.raises(http.FetchFailure, match="Unexpected Arcantel list"):
        arc.render(client, within_source(polite, source()), source(), PAGE)


def test_response_size_is_bounded(monkeypatch):
    monkeypatch.setattr(arc.discovery, "MAX_HTML_BYTES", 50)
    client, polite, _ = client_for(monkeypatch)
    with client, pytest.raises(http.FetchFailure, match="exceeds discovery limit"):
        arc.render(client, within_source(polite, source()), source(), PAGE)
