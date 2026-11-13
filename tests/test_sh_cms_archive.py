import json
from types import SimpleNamespace

import httpx
import pytest

from opencommune.config import settings
from opencommune.crawl import http, linked_archive
from opencommune.crawl.sites.sh_cms import document_urls, file_node_urls

LISTING = "https://oberhallau.ch/CMS/content?contentid=4347105&language=DE"
FILE = "https://oberhallau.ch/CMS/content?contentid=9001&language=DE"
PDF = "https://oberhallau.ch/CMS/get/file/40a67fda-66d2-4571-86b5-66fc09f49fdd"


def test_only_explicit_document_buttons_are_followed():
    widget = [
        {
            "type": "contentButtonAdder",
            "data": {
                "title": "Gemeindeversammlung",
                "customLabels": [{"contentid": "9001", "label": "Budget"}],
                "buttons": [
                    {"contentid": "9001", "contenttypeid": "101"},
                    {"contentid": "9002", "contenttypeid": "101"},
                    {"contentid": "9003", "contenttypeid": "10400"},
                ],
            },
        }
    ]
    payload = json.dumps({"contentid": "4347105", "data_widget_data": json.dumps(widget)})
    assert file_node_urls(payload, LISTING) == [FILE, FILE.replace("9001", "9002")]
    assert file_node_urls(payload, LISTING.replace("4347105", "123")) == []
    assert file_node_urls(payload, "https://oberhallau.ch/CMS/search?contentid=4347105") == []


def test_published_category_follows_only_visible_download_ids():
    root = {
        "contentid": "4347105",
        "contenttypeid": "499",
        "data_published": "published",
        "data_widget_data": json.dumps(
            [
                {
                    "type": "contentButtonAdder",
                    "data": {
                        "buttons": [
                            {"contentid": "7000", "contenttypeid": "402"},
                            {"contentid": "8000", "contenttypeid": "499"},
                        ]
                    },
                }
            ]
        ),
    }
    category_url = "https://oberhallau.ch/CMS/content?contentid=7000&language=DE"
    assert file_node_urls(json.dumps(root), LISTING) == [category_url]
    root["data_published"] = ""
    assert file_node_urls(json.dumps(root), LISTING) == [category_url]
    category = {
        "contentid": "7000",
        "contenttypeid": "402",
        "data_published": "published",
        "data_widget_data": json.dumps(
            [
                {
                    "type": "contentListGenerator",
                    "data": {
                        "contenttypes": [
                            {
                                "key": "downloads",
                                "visible": True,
                                "contentids": [
                                    "9001",
                                    "9002",
                                    "0",
                                    "-3",
                                    "abc",
                                    "\uff19\uff10\uff10\uff14",
                                ],
                                "unvisibleIds": ["9002"],
                            },
                            {"key": "service", "visible": True, "contentids": ["9005"]},
                            {"key": "downloads", "visible": False, "contentids": ["9006"]},
                        ]
                    },
                }
            ]
        ),
    }
    assert file_node_urls(json.dumps(category), category_url) == [FILE]
    category["data_published"] = "draft"
    assert file_node_urls(json.dumps(category), category_url) == []


def test_linked_archive_follows_published_category_to_pdf(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    settings.ensure_dirs()
    monkeypatch.setattr(http.Politeness, "wait", lambda self, url: None)
    monkeypatch.setattr(http, "ATTEMPTS", 1)
    entry = SimpleNamespace(bfs_id=1, name="Oberhallau", canton="SH")
    source = linked_archive.LinkedSource(
        bfs_id=1,
        website="https://oberhallau.ch",
        vendor="sh-cms",
        listing_urls=[LISTING],
        crawl_prefixes=["https://oberhallau.ch/CMS/content"],
    )
    category_url = "https://oberhallau.ch/CMS/content?contentid=7000&language=DE"
    hidden_url = FILE.replace("9001", "9002")
    root = {
        "contentid": "4347105",
        "contenttypeid": "499",
        "data_published": "published",
        "data_widget_data": json.dumps(
            [
                {
                    "type": "contentButtonAdder",
                    "data": {"buttons": [{"contentid": "7000", "contenttypeid": "402"}]},
                }
            ]
        ),
    }
    category = {
        "contentid": "7000",
        "contenttypeid": "402",
        "data_published": "published",
        "data_widget_data": json.dumps(
            [
                {
                    "type": "contentListGenerator",
                    "data": {
                        "contenttypes": [
                            {"key": "downloads", "visible": True, "contentids": ["9001", "9002"]}
                        ]
                    },
                }
            ]
        ),
    }
    published = {
        "contentid": "9001",
        "contenttypeid": "101",
        "data_published": "published",
        "data_filetype": "pdf",
        "data_filemeta": json.dumps(
            {
                "url": "/CMS/get/file/40a67fda-66d2-4571-86b5-66fc09f49fdd",
                "originalname": "Budget.pdf",
            }
        ),
    }
    unpublished = {**published, "contentid": "9002", "data_published": "draft"}
    seen = []

    def respond(request):
        url = str(request.url)
        seen.append(url)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        for target, node in [
            (LISTING, root),
            (category_url, category),
            (FILE, published),
            (hidden_url, unpublished),
        ]:
            if url == target:
                return httpx.Response(200, json=node)
        if url == PDF:
            return httpx.Response(
                200,
                content=b"%PDF-1.4\nfixture\n%%EOF",
                headers={"content-type": "application/pdf"},
            )
        return httpx.Response(404)

    with http.make_client(httpx.MockTransport(respond)) as client:
        state = linked_archive.fetch_one(
            source, entry, client, http.Politeness(client, 0, settings.ua), {}, limit=2
        )
    assert state["downloads"][PDF]["status"] == "held"
    assert all(
        state["pages"][url]["status"] == "ok" for url in (LISTING, category_url, FILE, hidden_url)
    )
    assert len(state["documents"]) == 1
    assert PDF in seen


def test_pdf_metadata_must_match_file_node_and_same_host():
    node = {
        "contentid": "9001",
        "contenttypeid": "101",
        "data_published": "published",
        "data_filetype": "pdf",
        "data_filemeta": json.dumps(
            {
                "url": "/CMS/get/file/40a67fda-66d2-4571-86b5-66fc09f49fdd",
                "originalname": "Budget.pdf",
            }
        ),
    }
    assert document_urls(json.dumps(node), FILE) == [PDF]
    assert document_urls(json.dumps(node), FILE.replace("9001", "9002")) == []
    node["data_filemeta"] = json.dumps(
        {"url": "https://elsewhere.ch/CMS/get/file/40a67fda-66d2-4571-86b5-66fc09f49fdd"}
    )
    assert document_urls(json.dumps(node), FILE) == []
    node["data_filemeta"] = json.dumps(
        {"url": "/CMS/get/file/40a67fda-66d2-4571-86b5-66fc09f49fdd"}
    )
    node["data_filetype"] = "jpg"
    assert document_urls(json.dumps(node), FILE) == []
    node["data_published"] = "draft"
    node["data_filetype"] = "pdf"
    assert document_urls(json.dumps(node), FILE) == []


def test_malformed_public_widget_and_pdf_metadata_raise():
    root = {"contentid": "4347105", "data_widget_data": "[{broken"}
    with pytest.raises(ValueError, match="widget JSON"):
        file_node_urls(json.dumps(root), LISTING)
    file_node = {
        "contentid": "9001",
        "contenttypeid": "101",
        "data_published": "published",
        "data_filetype": "pdf",
        "data_filemeta": "{broken",
    }
    with pytest.raises(ValueError, match="metadata JSON"):
        document_urls(json.dumps(file_node), FILE)


def test_linked_archive_follows_scoped_public_json_to_pdf(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    settings.ensure_dirs()
    monkeypatch.setattr(http.Politeness, "wait", lambda self, url: None)
    monkeypatch.setattr(http, "ATTEMPTS", 1)
    monkeypatch.setattr(linked_archive, "bfs_register", lambda: {1: ("Oberhallau", "SH")})
    entry = SimpleNamespace(bfs_id=1, name="Oberhallau", canton="SH")
    source = linked_archive.LinkedSource(
        bfs_id=1,
        website="https://oberhallau.ch",
        vendor="sh-cms",
        listing_urls=[LISTING],
        crawl_prefixes=["https://oberhallau.ch/CMS/content"],
    )
    widget = [
        {
            "type": "contentButtonAdder",
            "data": {"buttons": [{"contentid": "9001", "contenttypeid": "101"}]},
        }
    ]
    root = {"contentid": "4347105", "data_widget_data": json.dumps(widget)}
    node = {
        "contentid": "9001",
        "contenttypeid": "101",
        "data_published": "published",
        "data_filetype": "pdf",
        "data_filemeta": json.dumps({"url": "/CMS/get/file/40a67fda-66d2-4571-86b5-66fc09f49fdd"}),
    }
    calls = []

    def respond(request):
        url = str(request.url)
        calls.append(url)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        if url == LISTING:
            return httpx.Response(200, json=root)
        if url == FILE:
            return httpx.Response(200, json=node)
        if url == PDF:
            return httpx.Response(
                200,
                content=b"%PDF-1.4\nfixture\n%%EOF",
                headers={"content-type": "application/pdf"},
            )
        return httpx.Response(404)

    with http.make_client(httpx.MockTransport(respond)) as client:
        polite = http.Politeness(client, 0, settings.ua)
        state = linked_archive.fetch_one(source, entry, client, polite, {}, limit=2)
    assert state["downloads"][PDF]["status"] == "held"
    assert state["pages"][LISTING]["status"] == "ok"
    assert state["pages"][FILE]["status"] == "ok"
    assert state["documents"][PDF] == FILE
    assert PDF in calls
    sidecars = [json.loads(path.read_text()) for path in settings.raw_dir.glob("*.json")]
    assert len(sidecars) == 1 and sidecars[0]["listing_url"] == FILE


def test_linked_archive_reports_bad_json_and_obeys_robots(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    settings.ensure_dirs()
    monkeypatch.setattr(http.Politeness, "wait", lambda self, url: None)
    monkeypatch.setattr(http, "ATTEMPTS", 1)
    source = linked_archive.LinkedSource(
        bfs_id=1,
        website="https://oberhallau.ch",
        vendor="sh-cms",
        listing_urls=[LISTING],
        crawl_prefixes=["https://oberhallau.ch/CMS/content"],
    )
    entry = SimpleNamespace(bfs_id=1, name="Oberhallau", canton="SH")
    calls = []

    def respond(request):
        url = str(request.url)
        calls.append(url)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /CMS/content")
        if url == LISTING:
            return httpx.Response(200, json={"contentid": "wrong"})
        return httpx.Response(404)

    with http.make_client(httpx.MockTransport(respond)) as client:
        polite = http.Politeness(client, 0, settings.ua)
        state = linked_archive.fetch_one(source, entry, client, polite, {}, limit=1)
    assert state["status"] == "blocked"
    assert LISTING not in calls


def test_linked_archive_marks_mismatched_cms_json_as_schema_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    settings.ensure_dirs()
    monkeypatch.setattr(http.Politeness, "wait", lambda self, url: None)
    monkeypatch.setattr(http, "ATTEMPTS", 1)
    source = linked_archive.LinkedSource(
        bfs_id=1,
        website="https://oberhallau.ch",
        vendor="sh-cms",
        listing_urls=[LISTING],
        crawl_prefixes=["https://oberhallau.ch/CMS/content"],
    )
    entry = SimpleNamespace(bfs_id=1, name="Oberhallau", canton="SH")

    def respond(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        return httpx.Response(200, json={"contentid": "9001"})

    with http.make_client(httpx.MockTransport(respond)) as client:
        state = linked_archive.fetch_one(
            source, entry, client, http.Politeness(client, 0, settings.ua), {}, limit=1
        )
    assert state["pages"][LISTING]["kind"] == "api_schema"
