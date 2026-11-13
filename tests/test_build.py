import sqlite3

from opencommune import build
from opencommune.config import settings
from opencommune.crawl import access
from opencommune.db import _make_engine, init_db
from opencommune.register import Publication, RegisterEntry

REGISTER = [
    RegisterEntry(
        bfs_id=1,
        name="Alpha",
        canton="BE",
        status="blocked_robots",
        website="https://www.alpha.example",
        publications=[
            Publication(
                body="assembly",
                kind="minutes",
                status="blocked_robots",
                listing_url="https://www.alpha.example/protokolle",
                obstacle="robots.txt disallows the minutes listing",
            )
        ],
    ),
    # Two communes on one host: an observation there belongs to neither.
    RegisterEntry(bfs_id=2, name="Beta", canton="ZH", website="https://shared.example/beta"),
    RegisterEntry(bfs_id=3, name="Gamma", canton="ZH", website="https://shared.example/gamma"),
]


def test_build_writes_serving_tables_from_scratch(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(build, "load_register", lambda: REGISTER)
    db_path = tmp_path / "opencommune.db"
    engine = _make_engine(f"sqlite:///{db_path}")
    init_db(engine)
    engine.dispose()
    access.record("https://alpha.example/protokolle?page=2", "restricted")
    access.record("https://alpha.example/files/private-name.pdf", "rate_limited")
    access.record("https://shared.example/beta/files", "restricted")

    counts = build.run(db_path)
    assert counts == {"register": 3, "register_publications": 1, "access_observations": 1}
    assert build.run(db_path) == counts  # a rebuild replaces, never appends

    db = sqlite3.connect(db_path)
    assert db.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    status, note = db.execute("SELECT status, note FROM register WHERE bfs_id = 1").fetchone()
    assert status == "blocked_robots" and "robots.txt" in note
    # one row per website: the latest check's status, the restriction kept, no document address
    row = db.execute(
        "SELECT bfs_id, source_url, status, restricted_at IS NOT NULL FROM access_observations"
    ).fetchone()
    assert row == (1, "https://alpha.example/", "rate_limited", 1)
    db.close()
