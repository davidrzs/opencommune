import datetime as dt
import json
import sqlite3
from types import SimpleNamespace

from opencommune.crawl.coverage_report import build_report, checkpoint, markdown

TODAY = dt.date(2026, 9, 26)


def database():
    connection = sqlite3.connect(":memory:")
    connection.execute(
        "CREATE TABLE pdf_catalog (commune_bfs_id INTEGER, source_date TEXT, indexed_at TEXT)"
    )
    return connection


def entry(bfs):
    return SimpleNamespace(bfs_id=bfs, name=f"Commune {bfs}", canton="BE", vendor="custom")


def save(tmp_path, bfs, state, family="linked_archive"):
    path = tmp_path / "discovery" / family / f"{bfs}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"bfs_id": bfs, **state}))


def report(connection, tmp_path, configured, **kwargs):
    return build_report(
        connection,
        [entry(bfs) for bfs in configured],
        configured,
        tmp_path,
        today=TODAY,
        **kwargs,
    )


def test_dates_are_not_download_dates_and_unknown_is_not_recent(tmp_path):
    c = database()
    c.executemany(
        "INSERT INTO pdf_catalog VALUES (1, ?, ?)",
        [(None, "2026-09-26")] * 20 + [("2001-01-01", "2026-09-26"), ("2030-01-01", "2026-09-26")],
    )
    save(tmp_path, 1, {"status": "complete", "pages": {"x": {"status": "ok"}}})
    result = report(c, tmp_path, {1: {"linked_archive"}})
    row = result["communes"][0]
    assert row["pdfs"] == 22 and row["dated_pdfs"] == 1 and row["future_dated_pdfs"] == 1
    assert row["oldest_date"] == row["newest_date"] == "2001-01-01"
    assert row["action"] == "monitor"
    assert "incomplete_date_metadata" in row["signals"]
    assert "not necessarily the entire municipal archive" in markdown(result)


def test_queue_counts_do_not_treat_failed_or_nonpdf_as_unattempted():
    state = {
        "documents": dict.fromkeys(["held", "new", "failed", "nonpdf", "review"]),
        "downloads": {
            "held": {"status": "held"},
            "failed": {"status": "failed", "kind": "http"},
            "nonpdf": {"status": "not_pdf"},
        },
        "review_documents": {"review": "external"},
        "pages": {},
        "frontier": {"year2001": {}},
        "status": "pending",
    }
    row = checkpoint("linked_archive", state)
    assert (
        row["unattempted_urls"]
        == row["failed_urls"]
        == row["non_pdf_urls"]
        == row["held_urls"]
        == 1
    )
    assert row["pending_pages"] == 1 and not row["configured_scope_drained"]


def test_shallow_scope_and_pending_discovery_are_separate(tmp_path):
    c = database()
    c.executemany("INSERT INTO pdf_catalog VALUES (?, NULL, NULL)", [(1,), (2,)])
    save(tmp_path, 1, {"status": "complete", "pages": {"x": {"status": "ok"}}})
    save(tmp_path, 2, {"status": "pending", "frontier": {"x": {}}})
    rows = {
        r["bfs_id"]: r
        for r in report(c, tmp_path, {1: {"linked_archive", "curated"}, 2: {"linked_archive"}})[
            "communes"
        ]
    }
    assert rows[1]["action"] == "review_shallow_scope"
    assert rows[2]["action"] == "continue_discovery"


def test_missing_config_checkpoint_and_corrupt_state_are_distinct(tmp_path):
    c = database()
    save(tmp_path, 3, {"bfs_id": 999})
    result = report(c, tmp_path, {1: set(), 2: {"wordpress"}, 3: {"linked_archive"}})
    rows = {r["bfs_id"]: r for r in result["communes"]}
    assert rows[1]["action"] == "discover_missing"
    assert rows[2]["action"] == "continue_discovery"
    assert rows[3]["action"] == "resolve_failures"
    assert rows[3]["collectors"][0]["checkpoint_error"]


def test_access_observation_does_not_hide_work_on_other_paths(tmp_path):
    c = database()
    save(tmp_path, 1, {"status": "pending", "documents": {"x": "listing"}})
    result = report(
        c,
        tmp_path,
        {1: {"linked_archive"}, 2: set()},
        observations={1: ["restricted"], 2: ["restricted"]},
    )
    rows = {r["bfs_id"]: r for r in result["communes"]}
    assert rows[1]["action"] == "resume_downloads"
    assert "access_observation" in rows[1]["signals"]
    assert rows[2]["action"] == "resolve_access"


def test_saved_robots_failure_needs_review_before_recommending_more_requests(tmp_path):
    c = database()
    save(
        tmp_path,
        1,
        {
            "status": "running",
            "documents": {"old": {}, "new": {}},
            "downloads": {"old": {"status": "failed", "kind": "robots"}},
            "pending": ["page"],
        },
        family="wordpress",
    )
    row = report(c, tmp_path, {1: {"wordpress"}}, observations={1: ["restricted"]})["communes"][0]
    assert row["action"] == "resolve_access"
    assert row["collectors"][0]["unattempted_urls"] == 1


def test_incomplete_saved_running_state_is_not_called_drained(tmp_path):
    c = database()
    save(tmp_path, 1, {"status": "running", "pages": {"x": {"status": "ok"}}})
    row = report(c, tmp_path, {1: {"linked_archive"}})["communes"][0]
    assert row["action"] == "inspect_untracked"
