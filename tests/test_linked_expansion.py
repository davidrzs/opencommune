"""Adding reviewed sources must preserve prior downloads and identity boundaries."""

import json
from types import SimpleNamespace

import httpx
import pytest

from opencommune.config import settings
from opencommune.crawl import http
from opencommune.crawl import linked_archive as archive


def test_additive_configuration_resumes_without_redownloading(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    settings.ensure_dirs()
    monkeypatch.setattr(http.Politeness, "wait", lambda *args: None)
    host = "https://example.test"
    config = archive.LinkedSource(
        bfs_id=1, website=host, vendor="custom", listing_urls=[host + "/old"]
    )
    calls = []

    def respond(request):
        calls.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        if request.url.path in ["/old", "/extra"]:
            return httpx.Response(200, text=f'<a href="{request.url.path}.pdf">Download</a>')
        return httpx.Response(200, content=b"%PDF-1.4\n" + request.url.path.encode())

    with http.make_client(httpx.MockTransport(respond)) as client:
        polite = http.Politeness(client, 0, settings.ua)
        args = (SimpleNamespace(name="Example", canton="ZH"), client, polite)
        index = {}
        archive.fetch_one(config, *args, index, limit=10)
        expanded = config.model_copy(
            update={
                "listing_urls": [host + "/old", host + "/extra"],
                "document_urls": [host + "/selected.pdf"],
            }
        )
        state = archive.fetch_one(expanded, *args, index, limit=10)
        assert len(state["downloads"]) == 3
        assert calls.count("/old") == calls.count("/old.pdf") == 1
        assert state["source"] == json.loads(
            expanded.model_dump_json(
                exclude={
                    "document_url_prefixes",
                    "crawl_prefixes",
                    "external_listing_prefixes",
                    "wix_file_owner",
                    "finsta_exports",
                    "max_pages",
                    "max_depth",
                }
            )
        )
        with pytest.raises(ValueError, match="configuration changed"):
            archive.fetch_one(config, *args, index, limit=10)
