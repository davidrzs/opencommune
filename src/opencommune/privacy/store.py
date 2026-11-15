"""The privacy database, DATA_DIR/privacy.db: what the privacy check found on each page.

Only `opencommune privacy import` writes it. A run is a privacy queue; importing it again replaces
its rows, so a queue can be imported while it is still being worked on. A finding holds the
SHA-256 of the text that was checked, so the index build uses it only for that same text.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from ..text.queue import Queue

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    name TEXT PRIMARY KEY,          -- the queue's name
    created TEXT NOT NULL,          -- when the queue was made
    settings TEXT NOT NULL,         -- JSON: the queue's settings.json
    imported_at TEXT NOT NULL,      -- the last import
    pages INTEGER NOT NULL          -- finding rows after the last import
);
CREATE TABLE IF NOT EXISTS findings (
    sha256 TEXT NOT NULL,
    page INTEGER NOT NULL,
    run TEXT NOT NULL REFERENCES runs (name),
    status TEXT NOT NULL,           -- ok, or error (the latest)
    text_sha256 TEXT NOT NULL,      -- SHA-256 of the checked text (UTF-8)
    spans TEXT,                     -- JSON, when ok: [label, start, end, score] per span
    detail TEXT NOT NULL,           -- JSON: everything else the worker recorded
    PRIMARY KEY (sha256, page, run)
);
"""

FIELDS = ("sha256", "page", "status", "text_sha256", "spans")
BATCH = 10_000


def connect(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode = WAL")
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(SCHEMA)
    return db


def import_queue(db: sqlite3.Connection, name: str, queue: Queue) -> dict:
    """A privacy queue from `opencommune privacy queue`, with the answers it has so far."""
    insert = "INSERT INTO findings VALUES (?, ?, ?, ?, ?, ?, ?)"
    with db:
        db.execute("DELETE FROM findings WHERE run = ?", (name,))
        db.execute(
            "INSERT INTO runs VALUES (?, ?, ?, ?, 0) ON CONFLICT (name) DO UPDATE SET "
            "created = excluded.created, settings = excluded.settings, "
            "imported_at = excluded.imported_at",
            (
                name,
                queue.settings["created"],
                json.dumps(queue.settings, ensure_ascii=False),
                datetime.now(UTC).isoformat(timespec="seconds"),
            ),
        )
        rows: list[tuple] = []
        for chunk in queue.chunks():
            for record, _tries in queue.counting(chunk).values():
                spans = record.get("spans")
                detail = {key: value for key, value in record.items() if key not in FIELDS}
                rows.append(
                    (
                        record["sha256"],
                        record["page"],
                        name,
                        record["status"],
                        record["text_sha256"],
                        None if spans is None else json.dumps(spans, ensure_ascii=False),
                        json.dumps(detail, ensure_ascii=False),
                    )
                )
            if len(rows) >= BATCH:
                db.executemany(insert, rows)
                rows.clear()
        db.executemany(insert, rows)
        counts = dict(
            db.execute(
                "SELECT status, count(*) FROM findings WHERE run = ? GROUP BY status", (name,)
            )
        )
        db.execute("UPDATE runs SET pages = ? WHERE name = ?", (sum(counts.values()), name))
    return {"run": name, "pages": counts}
