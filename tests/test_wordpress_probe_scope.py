"""Scope selection stays separate from the verified WordPress availability report."""

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from opencommune.crawl import http

spec = importlib.util.spec_from_file_location(
    "wordpress_probe_scope", Path(__file__).resolve().parents[1] / "scripts" / "probe_wordpress.py"
)
wp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wp)


@pytest.mark.parametrize(
    ("args", "ids", "filename", "scope", "missing"),
    [
        ([], [1], "probe.json", "wordpress", 1),
        (["--scope", "unclassified"], [3, 4], "probe-unclassified.json", "unclassified", 2),
        (
            ["--scope", "unclassified", "--commune", "1,3,6"],
            [3],
            "probe-unclassified.json",
            "unclassified",
            1,
        ),
    ],
)
def test_scope_selection_reports_and_missing_websites(
    tmp_path, monkeypatch, capsys, args, ids, filename, scope, missing
):
    entries = [
        SimpleNamespace(bfs_id=i, vendor=vendor, website=website)
        for i, vendor, website in [
            (1, "wordpress", "https://wordpress.test"),
            (2, "wordpress", None),
            (3, "custom", "https://custom.test"),
            (4, None, "https://unknown.test"),
            (5, "i-web", "https://iweb.test"),
            (6, None, None),
            (7, "custom", ""),
        ]
    ]
    monkeypatch.setattr(wp.settings, "data_dir", tmp_path)
    monkeypatch.setattr(wp, "load_register", lambda: entries)
    monkeypatch.setattr(sys, "argv", ["probe_wordpress.py", *args])
    monkeypatch.setattr(http, "ATTEMPTS", http.ATTEMPTS)
    folder = tmp_path / "discovery/wordpress"
    folder.mkdir(parents=True)
    reports = {"probe.json": {"100": {"status": "available"}}, "probe-unclassified.json": {}}
    for name, content in reports.items():
        (folder / name).write_text(json.dumps(content))

    def scan(selected, results, path, **kwargs):
        assert [e.bfs_id for e in selected] == ids
        assert path.name == filename
        assert results == reports[filename]

    monkeypatch.setattr(wp, "scan", scan)
    wp.main()
    summary = json.loads(capsys.readouterr().out)
    assert summary["scope"] == scope
    assert summary["selected"] == len(ids)
    assert summary["missing_website"] == missing
    for name, content in reports.items():
        assert json.loads((folder / name).read_text()) == content


@pytest.mark.parametrize("vendor", ["custom", None, "wordpress"])
def test_probe_evidence_preserves_original_vendor(vendor):
    entry = SimpleNamespace(
        bfs_id=1, name="Example", canton="VD", website="https://example.test", vendor=vendor
    )
    polite = SimpleNamespace(_network=lambda host: "1.2.3", allowed=lambda url: False)
    result = wp.probe(entry, None, polite)
    assert "original_vendor" in result
    assert result["original_vendor"] == vendor
    assert result["status"] == "robots"
