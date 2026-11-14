"""The text database, DATA_DIR/text.db: the text of every page from every text layer pass and OCR
queue, and which text counts for a page.

Only `opencommune text import` writes it. A run is `layer:<name>` or `ocr:<name>`; importing a run
again replaces its rows, so an OCR queue can be imported while it is still being worked on.

`page_text` gives one text per page: an OCR answer if one is ok, else the text layer. When several
OCR runs answered a page, the newest run counts. OCR answers that ran to the token limit count
too; their `finish_reason` is "length".
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .queue import Queue

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    name TEXT PRIMARY KEY,          -- layer:<name> or ocr:<name>
    kind TEXT NOT NULL CHECK (kind IN ('layer', 'ocr')),
    created TEXT NOT NULL,          -- when the pass started or the queue was made
    settings TEXT NOT NULL,         -- JSON: the pass's or the queue's settings.json
    imported_at TEXT NOT NULL,      -- the last import
    pages INTEGER NOT NULL          -- page rows after the last import
);
CREATE TABLE IF NOT EXISTS pages (
    sha256 TEXT NOT NULL,
    page INTEGER NOT NULL,
    run TEXT NOT NULL REFERENCES runs (name),
    status TEXT NOT NULL,           -- ok; for OCR also render_error, rejected, request_error
    chars INTEGER,                  -- non-space characters of the text
    finish_reason TEXT,             -- OCR: stop, or length when the page ran to the token limit
    text TEXT,
    detail TEXT NOT NULL,           -- JSON: everything else the run recorded for the page
    PRIMARY KEY (sha256, page, run)
);
CREATE INDEX IF NOT EXISTS pages_by_run ON pages (run, status);
CREATE TABLE IF NOT EXISTS unreadable (
    run TEXT NOT NULL REFERENCES runs (name),
    sha256 TEXT NOT NULL,
    error TEXT NOT NULL,
    PRIMARY KEY (run, sha256)
);
CREATE VIEW IF NOT EXISTS page_text AS
SELECT sha256, page, run, kind AS source, finish_reason, text FROM (
    SELECT p.sha256, p.page, p.run, r.kind, p.finish_reason, p.text,
           row_number() OVER (
               PARTITION BY p.sha256, p.page ORDER BY r.kind = 'ocr' DESC, r.created DESC
           ) AS choice
    FROM pages p JOIN runs r ON r.name = p.run
    WHERE p.status = 'ok'
) WHERE choice = 1;
"""

PAGE_FIELDS = ("sha256", "page", "status", "finish_reason", "text", "chars")


def connect(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode = WAL")
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(SCHEMA)
    return db


def _chars(text: str | None) -> int | None:
    return None if text is None else sum(not c.isspace() for c in text)


def _row(run: str, record: dict, status: str) -> tuple:
    text = record.get("text")
    detail = {key: value for key, value in record.items() if key not in PAGE_FIELDS}
    chars = record["chars"] if "chars" in record else _chars(text)
    return (
        record["sha256"],
        record["page"],
        run,
        status,
        chars,
        record.get("finish_reason"),
        text,
        json.dumps(detail, ensure_ascii=False),
    )


BATCH = 10_000


def _replace(
    db: sqlite3.Connection, run: str, kind: str, settings: dict, created: str, rows
) -> dict:
    """Replace the run's rows in one transaction; return its pages by status."""
    inserts = {
        "pages": "INSERT OR REPLACE INTO pages VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        "unreadable": "INSERT OR REPLACE INTO unreadable VALUES (?, ?, ?)",
    }
    with db:
        db.execute("DELETE FROM pages WHERE run = ?", (run,))
        db.execute("DELETE FROM unreadable WHERE run = ?", (run,))
        db.execute(
            "INSERT INTO runs VALUES (?, ?, ?, ?, ?, 0) ON CONFLICT (name) DO UPDATE SET "
            "created = excluded.created, settings = excluded.settings, "
            "imported_at = excluded.imported_at",
            (
                run,
                kind,
                created,
                json.dumps(settings, ensure_ascii=False),
                datetime.now(UTC).isoformat(timespec="seconds"),
            ),
        )
        pending: dict[str, list[tuple]] = {"pages": [], "unreadable": []}
        for table, row in rows:
            pending[table].append(row)
            if len(pending[table]) >= BATCH:
                db.executemany(inserts[table], pending[table])
                pending[table].clear()
        for table, batch in pending.items():
            db.executemany(inserts[table], batch)
        counts = dict(
            db.execute("SELECT status, count(*) FROM pages WHERE run = ? GROUP BY status", (run,))
        )
        db.execute("UPDATE runs SET pages = ? WHERE name = ?", (sum(counts.values()), run))
        unreadable = db.execute("SELECT count(*) FROM unreadable WHERE run = ?", (run,)).fetchone()
    return {"run": run, "pages": counts, "unreadable_documents": unreadable[0]}


def import_layer(db: sqlite3.Connection, name: str, root: Path) -> dict:
    """A text layer pass from `opencommune text layer` (its directory `root`)."""
    settings = json.loads((root / "settings.json").read_text())
    run = f"layer:{name}"

    def rows():
        with (root / "pages.jsonl").open() as lines:
            for line in lines:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:  # cut off when the pass stopped; read again later
                    continue
                if "error" in record:
                    yield "unreadable", (run, record["sha256"], record["error"])
                else:
                    yield "pages", _row(run, record, "ok")

    return _replace(db, run, "layer", settings, settings["started"], rows())


def import_queue(db: sqlite3.Connection, name: str, queue: Queue) -> dict:
    """An OCR queue from `opencommune text queue`, with the answers it has so far."""
    run = f"ocr:{name}"

    def rows():
        for chunk in queue.chunks():
            for record, _tries in queue.counting(chunk).values():
                yield "pages", _row(run, record, record["status"])

    return _replace(db, run, "ocr", queue.settings, queue.settings["created"], rows())
