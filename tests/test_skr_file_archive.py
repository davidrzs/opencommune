"""Only reviewed widget JSON yields scoped opaque PDF candidates."""

import json

import httpx

from opencommune import register
from opencommune.config import settings
from opencommune.crawl import http, linked_archive, store
from opencommune.crawl.html_parse import parse_html
from opencommune.crawl.sites.skr_file import document_urls
from opencommune.register import RegisterEntry


def test_extracts_id_matched_routes_from_widget_json_without_js_execution():
    html = """<div x-data='skrListFileManager({"A":[
      {"id":4277,"name":"Arbeitszeitverordnung","url":"/datei-download/4277/arbeitszeitverordnung"},
      {"id":40,"name":"Abwasserreglement","url":"/datei-download/40/abwasserreglement"}
    ]},&apos;name&apos;,&apos;asc&apos;)'></div>"""
    assert document_urls(parse_html(html), "https://city.test/wir-fuer-sie/reglemente-a-z") == [
        "https://city.test/datei-download/40/abwasserreglement",
        "https://city.test/datei-download/4277/arbeitszeitverordnung",
    ]


def test_rejects_external_wrong_id_query_and_unrelated_routes():
    html = """<div x-data='skrListFileManager({"A":[
      {"id":1,"url":"https://other.test/datei-download/1/file"},
      {"id":2,"url":"/datei-download/3/wrong-id"},
      {"id":4,"url":"/datei-download/4/file?delete=1"},
      {"id":5,"url":"/admin/datei-download/5/file"},
      {"id":6,"url":"/datei-download/6/../private"},
      {"id":7,"url":"/datei-download/7/document"}
    ]})'></div>"""
    assert document_urls(parse_html(html), "https://city.test/archive") == [
        "https://city.test/datei-download/7/document"
    ]


def test_invalid_or_unrelated_widget_is_ignored():
    html = """<div x-data='otherManager({"A":[{"id":1,"url":"/datei-download/1/doc"}]})'></div>
    <div x-data='skrListFileManager({broken})'></div>
    <div x-data='skrListFileManager({"A":[{"id":2,"url":"/datei-download/2/doc"}]}); evil()'></div>"""
    assert document_urls(parse_html(html), "https://city.test/archive") == []


def test_malformed_entry_does_not_hide_valid_pdf_in_same_widget():
    giant_id = "9" * 5000
    entries = [
        {"id": 1, "url": "http://["},
        {"id": 2, "url": f"/datei-download/{giant_id}/oversized"},
        {"id": True, "url": "/datei-download/1/boolean-id"},
        {"id": 4277, "url": "/datei-download/4277/arbeitszeitverordnung"},
    ]
    html = f'<div x-data="skrListFileManager({json.dumps({"A": entries}).replace(chr(34), "&quot;")})"></div>'
    assert document_urls(parse_html(html), "https://city.test/archive") == [
        "https://city.test/datei-download/4277/arbeitszeitverordnung"
    ]


def test_linked_archive_fetches_widget_pdf_with_listing_provenance(tmp_path, monkeypatch):
    host = "https://city.test"
    listing = host + "/wir-fuer-sie/reglemente-a-z"
    pdf = host + "/datei-download/4277/arbeitszeitverordnung"
    html = """<div x-data='skrListFileManager({"A":[
      {"id":4277,"url":"/datei-download/4277/arbeitszeitverordnung"},
      {"id":4280,"url":"https://other.test/datei-download/4280/other"}
    ]})'></div>"""
    source = linked_archive.LinkedSource(
        bfs_id=1, website=host, vendor="custom", listing_urls=[listing]
    )
    assert linked_archive.documents(html, listing, source) == {pdf: listing}

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    settings.ensure_dirs()
    monkeypatch.setattr(http.Politeness, "wait", lambda self, url: None)
    monkeypatch.setattr(http, "ATTEMPTS", 1)
    monkeypatch.setattr(linked_archive, "bfs_register", lambda: {1: ("City", "ZH")})
    entry = RegisterEntry(bfs_id=1, name="City", canton="ZH", website=host, vendor="custom")
    monkeypatch.setattr(register, "load_register", lambda: [entry])
    calls = []

    def respond(request):
        url = str(request.url)
        calls.append(url)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        if url == listing:
            return httpx.Response(200, text=html)
        if url == pdf:
            return httpx.Response(200, content=b"%PDF-1.4\nwidget\n%%EOF")
        return httpx.Response(404)

    with http.make_client(httpx.MockTransport(respond)) as client:
        polite = http.Politeness(client, 0, settings.ua)
        state = linked_archive.fetch_one(source, entry, client, polite, store.load_index(), limit=2)
    assert state["downloads"][pdf]["status"] == "held"
    assert state["documents"][pdf] == listing
    assert not any("other.test" in url for url in calls)
