"""Concurrent archive downloads preserve deduplication and publish valid metadata."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import httpx
import pytest

from opencommune.config import settings
from opencommune.crawl import http, linked_archive, store
from opencommune.schemas import DocumentLink


@pytest.mark.parametrize("same_url", [True, False])
def test_concurrent_downloads_share_one_pdf_and_preserve_index(tmp_path, monkeypatch, same_url):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    settings.ensure_dirs()
    barrier = threading.Barrier(2)
    requests = []

    def respond(request):
        requests.append(str(request.url))
        if not same_url:
            barrier.wait(timeout=5)
        return httpx.Response(200, content=b"%PDF-1.4\nidentical PDF\n%%EOF")

    polite = SimpleNamespace(allowed=lambda url: True, wait=lambda url: None, requests=0)
    commune = SimpleNamespace(bfs_id=1)
    index = {}
    urls = [
        "https://example.test/a.pdf",
        "https://example.test/a.pdf" if same_url else "https://example.test/b.pdf",
    ]
    with http.make_client(httpx.MockTransport(respond)) as client:

        def download(url):
            return store._download(
                DocumentLink(
                    url=url, listing_url=url, title="", body="unknown", adapter="linked_archive"
                ),
                commune,
                client,
                polite,
                index,
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(download, urls))
    assert len(requests) == (1 if same_url else 2)
    assert len(list(settings.raw_dir.glob("*.pdf"))) == 1
    assert not list(settings.raw_dir.glob("*.part"))
    assert set(store.load_index()) == set(urls)
    records = [json.loads(line) for line in store.index_path().read_text().splitlines()]
    assert len(records) == len(set(urls))
    sha = records[0]["sha256"]
    assert json.loads((settings.raw_dir / f"{sha}.json").read_text())["sha256"] == sha


def test_linked_workers_overlap_independent_communes(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    sources = [SimpleNamespace(bfs_id=i) for i in (1, 2)]
    monkeypatch.setattr(linked_archive, "validate_sources", lambda sources: sources)
    monkeypatch.setattr(
        linked_archive,
        "load_register",
        lambda: [SimpleNamespace(bfs_id=i, name=str(i)) for i in (1, 2)],
    )
    barrier = threading.Barrier(2)

    def fetch_one(*args, **kwargs):
        barrier.wait(timeout=5)
        return {"status": "complete", "downloads": {}, "documents": {}}

    monkeypatch.setattr(linked_archive, "fetch_one", fetch_one)
    output = []
    linked_archive.run_fetch(sources, workers=2, emit=output.append)
    assert {json.loads(line)["bfs_id"] for line in output} == {1, 2}


def test_refresh_visits_oldest_communes_before_recently_checked_ones(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    sources = [SimpleNamespace(bfs_id=i) for i in (1, 2)]
    monkeypatch.setattr(linked_archive, "validate_sources", lambda sources: sources)
    monkeypatch.setattr(
        linked_archive,
        "load_register",
        lambda: [SimpleNamespace(bfs_id=i, name=str(i)) for i in (1, 2)],
    )
    monkeypatch.setattr(
        linked_archive,
        "read",
        lambda bfs: {"refreshed_at": "2026-09-12" if bfs == 1 else "2026-09-10", "downloads": {}},
    )
    visited = []

    def fetch_one(source, *args, **kwargs):
        assert kwargs["refresh"]
        visited.append(source.bfs_id)
        return {"status": "complete", "downloads": {}, "documents": {}}

    monkeypatch.setattr(linked_archive, "fetch_one", fetch_one)
    linked_archive.run_fetch(sources, refresh=True, emit=lambda _: None)
    assert visited == [2, 1]


def test_scheduling_releases_checkpoint_inventories_before_loading_index(tmp_path, monkeypatch):
    """A large archive must not retain every parsed checkpoint alongside the URL index."""
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    sources = [SimpleNamespace(bfs_id=i) for i in range(20)]
    monkeypatch.setattr(linked_archive, "validate_sources", lambda sources: sources)
    monkeypatch.setattr(
        linked_archive,
        "load_register",
        lambda: [SimpleNamespace(bfs_id=i, name=str(i)) for i in range(20)],
    )
    import weakref

    references = []

    class Inventory(dict):
        pass

    def read(bfs):
        assert not any(ref() is not None for ref in references)
        inventory = Inventory(downloads={"document": {"status": "held"}})
        references.append(weakref.ref(inventory))
        return inventory

    def load_index():
        assert not any(ref() is not None for ref in references)
        return {}

    monkeypatch.setattr(linked_archive, "read", read)
    monkeypatch.setattr(store, "load_index", load_index)
    monkeypatch.setattr(
        linked_archive,
        "fetch_one",
        lambda *args, **kwargs: {"status": "complete", "downloads": {}, "documents": {}},
    )
    linked_archive.run_fetch(sources, emit=lambda line: None)


def test_changed_configuration_skips_only_that_source(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    sources = [SimpleNamespace(bfs_id=i) for i in (1, 2)]
    monkeypatch.setattr(linked_archive, "validate_sources", lambda sources: sources)
    monkeypatch.setattr(
        linked_archive,
        "load_register",
        lambda: [SimpleNamespace(bfs_id=i, name=str(i)) for i in (1, 2)],
    )

    def fetch_one(source, *args, **kwargs):
        if source.bfs_id == 1:
            raise linked_archive.ConfigurationChanged("1: configuration changed")
        return {"status": "complete", "downloads": {}, "documents": {}}

    monkeypatch.setattr(linked_archive, "fetch_one", fetch_one)
    output = []
    linked_archive.run_fetch(sources, workers=1, emit=output.append)
    rows = {json.loads(line)["bfs_id"]: json.loads(line) for line in output}
    assert rows[1] == {"bfs_id": 1, "status": "configuration_changed"}
    assert rows[2]["status"] == "complete"
