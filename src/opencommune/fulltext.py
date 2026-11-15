"""The full-text index, DATA_DIR/fulltext.db: the text of the pages the search covers.

`run` writes it from scratch into a new file and renames that over the old index only when it is
complete. It reads the serving database and text.db and changes neither.

A page is indexed when it lies inside a section of one of `TYPES`, its document is not a bulletin
and not from a private body, and its text has at least `MIN_CHARS` non-space characters. A page
inside two sections is indexed once. Section types, communes, years and dates are not copied: the
server joins the serving database on sha256 and page.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
from collections import defaultdict
from contextlib import closing
from datetime import UTC, datetime
from itertools import groupby
from pathlib import Path

log = logging.getLogger(__name__)

# The section types the search covers: deliberation, money and proposals.
TYPES = (
    "minutes",
    "decisions",
    "vote_result",
    "budget",
    "accounts",
    "proposal",
    "invitation_agenda",
    "member_request",
)
# A page with less text has no usable text layer. OCR will give it text later.
MIN_CHARS = 20

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
    f"A page is indexed when it lies inside a section of one of these types: {', '.join(TYPES)}. "
    "The sections come from the serving database. "
    "Documents whose kind is bulletin are left out. "
    "Documents whose body is private are left out. "
    f"Pages whose text has fewer than {MIN_CHARS} non-space characters are left out. "
    "The text is the page_text of text.db: the OCR answer if one is ok, else the text layer. "
    "A word split at a line end is joined: a letter, '-', a line break and a lower-case letter "
    "become one word, unless the next word is und, oder, bis, bzw or sowie (a shortened compound "
    "such as 'Ein- und Ausgaben'). Nothing else in the text is changed. "
    "A page inside two sections is indexed once."
)

BATCH = 10_000

# A hyphen and a line break between two word characters; `join_split_words` checks the letters.
_SPLIT = re.compile(r"(?<=\w)-\n(?=\w)")
# A hyphen before these words shortens a compound ("Ein- und Ausgaben"); it is not a split word.
_SHORTENED = re.compile(r"(?:und|oder|bis|bzw|sowie)\b")


def join_split_words(text: str) -> str:
    r"""Join the words split at a line end: a letter, '-', a line break and a lower-case letter
    become one word. "Gemeinde-\nrat" becomes "Gemeinderat". "Gemeinde-\nRat" stays as it is, and
    so does "Ein-\nund Ausgaben"."""

    def join(match: re.Match) -> str:
        before, after = text[match.start() - 1], text[match.end()]
        if before.isalpha() and after.islower() and not _SHORTENED.match(text, match.end()):
            return ""
        return match[0]

    return _SPLIT.sub(join, text)


def page_texts(text_db: sqlite3.Connection, sha256: str) -> sqlite3.Cursor:
    """(page, source, run, text) for each page of the document that text.db has text for.

    The index takes its text from here and nowhere else: the `page_text` view, which gives the
    OCR answer if one is ok, else the text layer. A redaction run will replace the text here."""
    return text_db.execute(
        "SELECT page, source, run, text FROM page_text WHERE sha256 = ? ORDER BY page", (sha256,)
    )


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
        with (
            closing(_read_only(serving_path)) as serving,
            closing(_read_only(text_path)) as text,
            closing(sqlite3.connect(tmp)) as db,
        ):
            with db:
                db.executescript(SCHEMA)
                counts = _index(db, serving, text)
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


def _read_only(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def _sha256(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def _index(db: sqlite3.Connection, serving: sqlite3.Connection, text: sqlite3.Connection) -> dict:
    """Write the pages in scope into `pages` and `page_fts`; return the counts."""
    marks = ",".join("?" * len(TYPES))
    sections = serving.execute(
        "SELECT s.sha256, s.type, s.first_page, s.last_page, d.page_count "
        "FROM sections s JOIN documents d USING (sha256) "
        f"WHERE s.type IN ({marks}) AND d.kind IS NOT 'bulletin' AND d.body_kind IS NOT 'private' "
        "ORDER BY s.sha256",
        TYPES,
    )
    pages = {"in_sections": 0, "no_text": 0, "too_short": 0, "indexed": 0}
    by_type = {kind: {"pages": 0, "indexed": 0} for kind in TYPES}
    documents = 0
    rows: list[tuple] = []
    texts: list[tuple] = []
    for sha, group in groupby(sections, key=lambda row: row[0]):
        inside: dict[int, set[str]] = defaultdict(set)
        for _, kind, first, last, page_count in group:
            first, last = min(first, last), max(first, last)
            for page in range(max(first, 1), min(last, page_count or last) + 1):
                inside[page].add(kind)
        for kinds in inside.values():
            for kind in kinds:
                by_type[kind]["pages"] += 1
        pages["in_sections"] += len(inside)
        found = indexed = 0
        for page, source, run_name, raw in page_texts(text, sha):
            kinds = inside.get(page)
            if kinds is None:
                continue
            found += 1
            if sum(map(len, (raw or "").split())) < MIN_CHARS:
                pages["too_short"] += 1
                continue
            indexed += 1
            pages["indexed"] += 1
            for kind in kinds:
                by_type[kind]["indexed"] += 1
            rows.append((pages["indexed"], sha, page, source, run_name))
            texts.append((pages["indexed"], join_split_words(raw)))
        pages["no_text"] += len(inside) - found
        if indexed:
            documents += 1
        if len(rows) >= BATCH:
            _insert(db, rows, texts)
            log.debug("fulltext: %d pages of %d documents", pages["indexed"], documents)
    _insert(db, rows, texts)
    return {"documents": documents, "pages": pages, "section_types": by_type}


def _insert(db: sqlite3.Connection, rows: list[tuple], texts: list[tuple]) -> None:
    db.executemany("INSERT INTO pages VALUES (?, ?, ?, ?, ?)", rows)
    db.executemany("INSERT INTO page_fts (rowid, text) VALUES (?, ?)", texts)
    rows.clear()
    texts.clear()
