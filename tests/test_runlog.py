"""The fetch run log (data/logs/fetch_runs.jsonl)."""

import json

import pytest

from opencommune.config import settings
from opencommune.crawl import runlog


@pytest.fixture
def logs(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    return settings.logs_dir


def line(bfs: int = 1, started: str = "2026-09-08T03:00:00+00:00", **fields) -> dict:
    base = {
        "started": started,
        "commune_bfs_id": bfs,
        "adapter": "html_links",
        "listing_url": "https://x.ch/p",
        "dry_run": False,
        "listing_status": "ok",
        "new": 0,
        "errors": [],
        "links": [],
    }
    return {**base, **fields}


def test_without_a_log_there_are_no_runs(logs):
    assert list(runlog.read_runs()) == [] and runlog.last_runs() == {}


def test_last_runs_keeps_the_newest_real_run_per_source(logs):
    runlog.append(line(started="2026-09-01T03:00:00+00:00", new=1))
    runlog.append(line(new=0))
    runlog.append(line(started="2026-09-09T03:00:00+00:00", dry_run=True))
    runlog.append(line(bfs=2, adapter="wp_media"))
    assert (logs / "fetch_runs.jsonl").exists()
    last = runlog.last_runs()
    assert set(last) == {(1, "html_links", "https://x.ch/p"), (2, "wp_media", "https://x.ch/p")}
    assert last[(1, "html_links", "https://x.ch/p")]["started"] == "2026-09-08T03:00:00+00:00"
    assert (
        runlog.last_runs(include_dry=True)[(1, "html_links", "https://x.ch/p")]["dry_run"] is True
    )


def test_a_line_cut_short_by_a_crash_is_skipped(logs):
    logs.mkdir(parents=True)
    (logs / "fetch_runs.jsonl").write_text(json.dumps(line()) + '\n{"started": "2026-09-08", "comm')
    assert len(list(runlog.read_runs())) == 1
