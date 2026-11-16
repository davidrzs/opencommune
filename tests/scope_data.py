"""A serving database, a text.db and a privacy.db for the tests of the search scope, OCR, the
privacy check and the index. A has sections of four types; one document is a bulletin, one from a
private body, and D has neither a kind nor a body kind."""

import hashlib
import json
import sqlite3
from contextlib import closing
from importlib.resources import files

from opencommune.privacy import detect
from opencommune.privacy import store as privacy_store
from opencommune.text import store

A, BULLETIN, PRIVATE, D = ("a" * 64, "b" * 64, "c" * 64, "d" * 64)
LONG = "Der Gemeinderat beantragt einen Kredit."

DOCUMENTS = [
    (A, 7, "meeting_booklet", "parliament"),
    (BULLETIN, 1, "bulletin", "commune"),
    (PRIVATE, 1, "standalone", "private"),
    (D, 1, None, None),
]
SECTIONS = [
    (A, 1, "budget", "money", 1, 2),
    (A, 2, "minutes", "deliberation", 3, 2),  # given in reverse; page 2 is in two
    (A, 3, "report", "information", 4, 4),  # not searched
    (A, 4, "proposal", "proposals", 6, 9),  # the document ends at page 7
    (BULLETIN, 1, "minutes", "deliberation", 1, 1),
    (PRIVATE, 1, "minutes", "deliberation", 1, 1),
    (D, 1, "decisions", "deliberation", 1, 1),
]
# Page 1 of A has a text layer and an OCR answer; page 7 has neither.
PAGES = [
    (A, 1, "layer:d", "Budget Zwischentext"),
    (A, 1, "ocr:q", "Crédit d'engagement pour la route"),
    (A, 2, "layer:d", "Der Gemeinde-\nrat beschliesst den Steuerfuss.\nGemeinde-\nRat"),
    (A, 3, "layer:d", " ".join("abcdefghijklmnopqrs")),  # 19 non-space characters
    (A, 4, "layer:d", LONG),
    (A, 5, "layer:d", LONG),
    (A, 6, "layer:d", "Antrag Tempo 30 auf der Hauptstrasse"),
    (BULLETIN, 1, "layer:d", LONG),
    (PRIVATE, 1, "layer:d", LONG),
    (D, 1, "layer:d", "Beschluss Nr. 123/2026"),  # 20 non-space characters
]


def serving_db(path, documents=DOCUMENTS, sections=SECTIONS):
    with closing(sqlite3.connect(path)) as db:
        db.executescript(files("opencommune").joinpath("serving.sql").read_text())
        db.execute("INSERT INTO runs VALUES ('cls', 'classification', 'm', '{}', 'note', 4)")
        db.executemany(
            "INSERT INTO documents (sha256, first_seen, page_count, run_id, kind, body_kind, "
            "personal_data) VALUES (?, '2026-01-01', ?, 'cls', ?, ?, 0)",
            documents,
        )
        db.executemany("INSERT INTO sections VALUES (?, ?, ?, ?, ?, ?, 0, 0)", sections)
        db.commit()
    return path


def text_db(path, pages=PAGES):
    """text.db with a text layer pass `layer:d` and an OCR run `ocr:q`."""
    with closing(store.connect(path)) as db:
        db.executemany(
            "INSERT INTO runs VALUES (?, ?, ?, '{}', ?, 0)",
            [
                ("layer:d", "layer", "2026-11-01T00:00:00+00:00", "2026-11-01T00:00:00+00:00"),
                ("ocr:q", "ocr", "2026-11-02T00:00:00+00:00", "2026-11-02T00:00:00+00:00"),
            ],
        )
        db.executemany(
            "INSERT INTO pages (sha256, page, run, status, text, detail) "
            "VALUES (?, ?, ?, 'ok', ?, '{}')",
            pages,
        )
        db.commit()
    return path


def privacy_db(path, serving, text, spans=lambda text: []):
    """privacy.db with one run `p` that checked every page in scope with usable text; `spans` gives
    the spans found in a page's text."""
    findings = [
        (item["sha256"], item["page"], hashlib.sha256(item["text"].encode()).hexdigest(), item)
        for item in detect.choose(serving, text)
    ]
    with closing(privacy_store.connect(path)) as db:
        db.execute(
            "INSERT INTO runs VALUES ('p', '2026-11-03T00:00:00+00:00', '{}', "
            "'2026-11-03T00:00:00+00:00', ?)",
            (len(findings),),
        )
        db.executemany(
            "INSERT INTO findings VALUES (?, ?, 'p', 'ok', ?, ?, '{}')",
            [
                (sha, page, digest, json.dumps(spans(item["text"])))
                for sha, page, digest, item in findings
            ],
        )
        db.commit()
    return path
