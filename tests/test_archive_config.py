"""Batch configuration is complete, attributable and atomic; no network is used."""

import json
from urllib.parse import parse_qs, urlsplit

import pytest
import yaml

from opencommune.crawl import archive_config, wordpress
from opencommune.register import RegisterEntry


@pytest.fixture
def batch(tmp_path, monkeypatch):
    entries = [
        RegisterEntry(
            bfs_id=1,
            name="Zeta",
            canton="ZH",
            website="https://zeta.test",
            vendor="wordpress",
            status="configured",
        ),
        RegisterEntry(
            bfs_id=2, name="Alpha", canton="BE", website="https://alpha.test", vendor="wordpress"
        ),
    ]
    identities = {1: ("Zeta", "ZH"), 2: ("Alpha", "BE")}
    monkeypatch.setattr(archive_config, "load_register", lambda: entries)
    monkeypatch.setattr(archive_config, "bfs_register", lambda: identities)
    monkeypatch.setattr(wordpress, "bfs_register", lambda: identities)
    rows = {
        str(e.bfs_id): {
            "bfs_id": e.bfs_id,
            "website": e.website,
            "canton": e.canton,
            "status": "available",
            "total": None,
            "endpoint": e.website
            + "/de/wp-json/wp/v2/media?_fields=id&page=1&per_page=3&mime_type=application/pdf",
            "sample_urls": [e.website + "/a.pdf"],
        }
        for e in entries
    }
    report, output = tmp_path / "report.json", tmp_path / "sources.yaml"
    output.write_text("[]\n")
    return rows, report, output


def configure(batch):
    rows, report, output = batch
    report.write_text(json.dumps(rows))
    return archive_config.configure_wordpress(report, output)


def test_complete_batch_includes_curated_and_sorts_by_canonical_identity(batch):
    result = configure(batch)
    assert result["configured"] == 2
    assert result["already_curated"] == 1
    assert result["statuses"] == {"available": 2}
    sources = yaml.safe_load(batch[2].read_text())
    assert [s["bfs_id"] for s in sources] == [2, 1]
    assert urlsplit(sources[0]["listing_url"]).path == "/de/wp-json/wp/v2/media"
    assert parse_qs(urlsplit(sources[0]["listing_url"]).query) == {
        "per_page": ["100"],
        "page": ["1"],
        "mime_type": ["application/pdf"],
    }


def test_regeneration_preserves_reviewed_pdf_scope_for_matching_source(batch):
    existing = {
        "bfs_id": 1,
        "website": "https://zeta.test",
        "adapter": "wp_media",
        "listing_url": "https://zeta.test/de/wp-json/wp/v2/media?mime_type=application%2Fpdf&page=1&per_page=100",
        "document_url_prefixes": ["https://files.test/wp-content/uploads/"],
        "attribution_note": "Reviewed municipal media directory",
    }
    batch[2].write_text(yaml.safe_dump([existing]))
    configure(batch)
    sources = {row["bfs_id"]: row for row in yaml.safe_load(batch[2].read_text())}
    assert sources[1]["document_url_prefixes"] == existing["document_url_prefixes"]
    assert sources[1]["attribution_note"] == existing["attribution_note"]
    assert sources[2]["document_url_prefixes"] == []


def test_regeneration_does_not_transfer_scope_to_changed_endpoint(batch):
    existing = {
        "bfs_id": 1,
        "website": "https://zeta.test",
        "adapter": "wp_media",
        "listing_url": "https://zeta.test/de/wp-json/wp/v2/media?page=2&per_page=100&mime_type=application%2Fpdf",
        "document_url_prefixes": ["https://files.test/wp-content/uploads/"],
        "attribution_note": "Reviewed municipal media directory",
    }
    batch[2].write_text(yaml.safe_dump([existing]))
    configure(batch)
    sources = {row["bfs_id"]: row for row in yaml.safe_load(batch[2].read_text())}
    assert sources[1]["document_url_prefixes"] == []
    assert sources[1]["attribution_note"] == ""


def test_incomplete_scan_does_not_replace_existing_configuration(batch):
    del batch[0]["2"]
    with pytest.raises(ValueError, match="incomplete"):
        configure(batch)
    assert batch[2].read_text() == "[]\n"


@pytest.mark.parametrize(
    "field,value",
    [
        ("bfs_id", 55),
        ("canton", "GR"),
        ("website", "http://zeta.test"),
        ("endpoint", "https://other.test/wp-json/wp/v2/media"),
        ("endpoint", "https://zeta.test/arbitrary"),
        ("sample_urls", []),
        ("sample_urls", ["https:broken"]),
        ("sample_urls", ["https://user:secret@zeta.test/a.pdf"]),
    ],
)
def test_invalid_available_source_leaves_output_untouched(batch, field, value):
    batch[0]["1"][field] = value
    with pytest.raises(ValueError):
        configure(batch)
    assert batch[2].read_text() == "[]\n"


def test_failures_and_empty_are_counted_without_becoming_sources(batch):
    batch[0]["1"]["status"] = "robots"
    batch[0]["2"]["status"] = "empty"
    result = configure(batch)
    assert result["configured"] == 0
    assert result["statuses"] == {"empty": 1, "robots": 1}
    assert yaml.safe_load(batch[2].read_text()) == []


def test_atomic_replace_failure_keeps_previous_file(batch, monkeypatch):
    def fail(*args):
        raise OSError("disk error")

    monkeypatch.setattr(archive_config.os, "replace", fail)
    with pytest.raises(OSError, match="disk error"):
        configure(batch)
    assert batch[2].read_text() == "[]\n"
    assert not list(batch[2].parent.glob(".sources.yaml.*"))
