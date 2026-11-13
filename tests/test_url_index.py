"""The append-only URL index (data/raw/urls.jsonl) and canonical URLs."""

import datetime as dt
import json

import pytest

from opencommune.config import settings
from opencommune.crawl import store
from opencommune.schemas import RawSidecar

SHA1, SHA2, SHA3 = "1" * 64, "2" * 64, "3" * 64


@pytest.fixture
def raw(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    settings.ensure_dirs()
    return settings.raw_dir


def entry(url: str, sha: str = SHA1, **fields) -> dict:
    base = {
        "url": url,
        "canonical_url": store.canonical_url(url),
        "sha256": sha,
        "etag": None,
        "last_modified": None,
        "fetched_at": "2026-09-08T00:00:00+00:00",
        "commune_bfs_id": 1,
        "adapter": "html_links",
    }
    return {**base, **fields}


def test_canonical_url_drops_volatile_parameters_and_keeps_the_rest():
    assert (
        store.canonical_url("https://x.ch/doc.pdf?tmstv=123&id=7&panntime=9#p3")
        == "https://x.ch/doc.pdf?id=7"
    )
    assert store.canonical_url("https://X.ch/a?rif=1&SID=2", ["sid"]) == "https://x.ch/a"
    assert store.canonical_url("https://x.ch/a?b=1&a=2") == "https://x.ch/a?b=1&a=2"  # order kept
    assert store.canonical_url("https://x.ch/a") == "https://x.ch/a"


def test_index_is_appended_and_reloaded_with_the_newest_entry_winning(raw):
    assert store.load_index() == {}
    index: dict = {}
    store._index_add(index, entry("https://x.ch/a.pdf?tmstv=1", SHA1))
    store._index_add(index, entry("https://x.ch/a.pdf?tmstv=2", SHA2))
    assert list(index) == ["https://x.ch/a.pdf"] and index["https://x.ch/a.pdf"]["sha256"] == SHA2
    assert store.load_index() == index
    assert len((raw / "urls.jsonl").read_text().splitlines()) == 2  # append-only: both lines kept


def test_a_line_cut_short_by_a_crash_is_skipped(raw):
    (raw / "urls.jsonl").write_text(
        json.dumps(entry("https://x.ch/a.pdf")) + '\n{"url": "https://x.ch/b.pdf", "canon'
    )
    assert list(store.load_index()) == ["https://x.ch/a.pdf"]


def test_rebuild_from_sidecars_uses_the_communes_volatile_parameters(raw):
    sidecar = RawSidecar(
        sha256=SHA3,
        source_url="https://x.ch/c.pdf?sid=9&tmstv=1",
        listing_url="https://x.ch/",
        commune_bfs_id=7,
        body="assembly",
        fetched_at=dt.datetime(2026, 9, 8, tzinfo=dt.UTC),
        size=10,
        listing_title="t",
        etag='"c"',
    )
    (raw / f"{SHA3}.json").write_text(sidecar.model_dump_json())
    (raw / "index.json").write_text("{}")  # not a sidecar
    (raw / "broken.json").write_text("{}")  # not a sidecar either
    index = store.rebuild_index({7: ["sid"]})
    assert list(index) == ["https://x.ch/c.pdf"]
    got = index["https://x.ch/c.pdf"]
    assert got["url"] == sidecar.source_url and got["sha256"] == SHA3 and got["etag"] == '"c"'
    assert (
        got["commune_bfs_id"] == 7
        and got["adapter"] is None
        and got["fetched_at"] == "2026-09-08T00:00:00+00:00"
    )
