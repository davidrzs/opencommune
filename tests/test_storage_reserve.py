from types import SimpleNamespace

import httpx
import pytest

from opencommune.config import settings
from opencommune.crawl import storage, store
from opencommune.schemas import DocumentLink


def capacity(monkeypatch, tmp_path, free):
    monkeypatch.setattr(settings, "raw_data_dir", tmp_path)
    monkeypatch.setattr(settings, "raw_min_free_bytes", 100)
    monkeypatch.setattr(storage.shutil, "disk_usage", lambda path: SimpleNamespace(free=free))


def test_reserve_blocks_new_network_download_and_keeps_known_files_usable(tmp_path, monkeypatch):
    capacity(monkeypatch, tmp_path, 99)
    link = DocumentLink(
        url="https://commune.test/budget.pdf",
        listing_url="https://commune.test",
        title="",
        body="unknown",
        adapter="linked_archive",
    )
    monkeypatch.setattr(
        store, "_open_document", lambda *args: pytest.fail("must not request a PDF")
    )
    with pytest.raises(storage.StorageReserveError):
        store._download(link, None, None, None, {})
    sha = "a" * 64
    (tmp_path / (sha + ".pdf")).write_bytes(b"%PDF-test")
    assert store._download(link, None, None, None, {link.url: {"sha256": sha}}) is None


def test_loss_of_capacity_mid_stream_removes_part_without_remote_failure(tmp_path, monkeypatch):
    capacity(monkeypatch, tmp_path, 100 + 2 * 1024**2)
    readings = iter([100 + 2 * 1024**2, 99])
    monkeypatch.setattr(
        storage.shutil, "disk_usage", lambda path: SimpleNamespace(free=next(readings))
    )
    response = httpx.Response(200, content=b"%PDF-" + b"x" * (2 * 1024**2))
    with pytest.raises(storage.StorageReserveError):
        store._stream_to_part(response, "https://commune.test/file.pdf")
    assert list(tmp_path.iterdir()) == []


def test_free_space_equal_to_required_capacity_is_allowed(tmp_path, monkeypatch):
    capacity(monkeypatch, tmp_path, 110)
    assert storage.require_space(10) == 110
    with pytest.raises(storage.StorageReserveError):
        storage.require_space(11)
