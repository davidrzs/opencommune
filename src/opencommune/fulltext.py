"""The full-text index, DATA_DIR/fulltext.db: the text of the pages the search covers.

`run` writes it from scratch into a new file and renames that over the old index only when it is
complete. It reads the serving database and text.db and changes neither.

The pages and their text come from `scope.pages`: a page is indexed when it is in scope and its
text is usable. A page inside two sections is indexed once. Section types, communes, years and
dates are not copied: the server joins the serving database on sha256 and page.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from . import scope

log = logging.getLogger(__name__)

SCHEMA = """
-- One row per indexed page. Its id is the rowid of the page's text in page_fts.
CREATE TABLE pages (
    id INTEGER PRIMARY KEY,
    sha256 TEXT NOT NULL,
    page INTEGER NOT NULL,          -- 1 for the first page
    source TEXT NOT NULL,           -- layer | ocr
    run TEXT NOT NULL,              -- the text.db run the text came from
    UNIQUE (sha256, page)
);
-- The text of each page. It is stored, so that the server can show snippets and whole pages.
CREATE VIRTUAL TABLE page_fts USING fts5(text, tokenize = 'unicode61 remove_diacritics 2');
-- How the file was built: the checksums of the inputs, the counts (JSON) and the rules.
CREATE TABLE build (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

RULES = (
    f"A page is indexed when it lies inside a section of one of these types: {', '.join(scope.TYPES)}. "
    "The sections come from the serving database. "
    "Documents whose kind is bulletin are left out. "
    "Documents whose body is private are left out. "
    f"Pages whose text has fewer than {scope.MIN_CHARS} non-space characters are left out. "
    "The text is the page_text of text.db: the OCR answer if one is ok, else the text layer. "
    "A word split at a line end is joined: a letter, '-', a line break and a lower-case letter "
    "become one word, unless the next word is und, oder, bis, bzw or sowie (a shortened compound "
    "such as 'Ein- und Ausgaben'). Nothing else in the text is changed. "
    "A page inside two sections is indexed once."
)

BATCH = 10_000


def run(fulltext_path: Path, serving_path: Path, text_path: Path) -> dict:
    """Write the index to `fulltext_path`; return the counts it records."""
    record = {
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "serving_db_sha256": _sha256(serving_path),
        "text_db_sha256": _sha256(text_path),
    }
    tmp = fulltext_path.with_name(fulltext_path.name + ".tmp")
    tmp.unlink(missing_ok=True)
    try:
        with closing(sqlite3.connect(tmp)) as db:
            with db:
                db.executescript(SCHEMA)
                counts = _index(db, scope.pages(serving_path, text_path))
                log.info("fulltext: merging the index")
                db.execute("INSERT INTO page_fts (page_fts) VALUES ('optimize')")
                rows = {**record, **{k: json.dumps(v) for k, v in counts.items()}, "rules": RULES}
                db.executemany("INSERT INTO build VALUES (?, ?)", rows.items())
            db.execute("PRAGMA journal_mode=DELETE")
        os.replace(tmp, fulltext_path)
    finally:
        tmp.unlink(missing_ok=True)
    log.info("fulltext: %d pages of %d documents", counts["pages"]["indexed"], counts["documents"])
    return counts


def _sha256(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def _index(db: sqlite3.Connection, pages_in_scope) -> dict:
    """Write the usable pages into `pages` and `page_fts`; return the counts."""
    pages = {"in_sections": 0, "no_text": 0, "too_short": 0, "indexed": 0}
    by_type = {kind: {"pages": 0, "indexed": 0} for kind in scope.TYPES}
    documents: set[str] = set()
    rows: list[tuple] = []
    texts: list[tuple] = []
    for page in pages_in_scope:
        pages["in_sections"] += 1
        for kind in page.types:
            by_type[kind]["pages"] += 1
        if page.raw is None:
            pages["no_text"] += 1
            continue
        if not page.usable:
            pages["too_short"] += 1
            continue
        pages["indexed"] += 1
        for kind in page.types:
            by_type[kind]["indexed"] += 1
        documents.add(page.sha256)
        rows.append((pages["indexed"], page.sha256, page.page, page.source, page.run))
        texts.append((pages["indexed"], page.text))
        if len(rows) >= BATCH:
            _insert(db, rows, texts)
            log.debug("fulltext: %d pages of %d documents", pages["indexed"], len(documents))
    _insert(db, rows, texts)
    return {"documents": len(documents), "pages": pages, "section_types": by_type}


def _insert(db: sqlite3.Connection, rows: list[tuple], texts: list[tuple]) -> None:
    db.executemany("INSERT INTO pages VALUES (?, ?, ?, ?, ?)", rows)
    db.executemany("INSERT INTO page_fts (rowid, text) VALUES (?, ?)", texts)
    rows.clear()
    texts.clear()
