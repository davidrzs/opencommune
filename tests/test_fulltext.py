import hashlib
import json
import sqlite3
from contextlib import closing
from importlib.resources import files

import pytest
from typer.testing import CliRunner

from opencommune import build, fulltext
from opencommune.cli import app
from opencommune.config import settings
from opencommune.text import store

A, BULLETIN, PRIVATE, D = ("a" * 64, "b" * 64, "c" * 64, "d" * 64)
LONG = "Der Gemeinderat beantragt einen Kredit."


def serving_db(path):
    """A serving database with four documents: A has sections of four types, one bulletin, one from
    a private body, and D without a kind or a body kind."""
    with closing(sqlite3.connect(path)) as db:
        db.executescript(files("opencommune").joinpath("serving.sql").read_text())
        db.execute("INSERT INTO runs VALUES ('cls', 'classification', 'm', '{}', 'note', 4)")
        db.executemany(
            "INSERT INTO documents (sha256, first_seen, page_count, run_id, kind, body_kind, "
            "personal_data) VALUES (?, '2026-01-01', ?, 'cls', ?, ?, 0)",
            [
                (A, 7, "meeting_booklet", "parliament"),
                (BULLETIN, 1, "bulletin", "commune"),
                (PRIVATE, 1, "standalone", "private"),
                (D, 1, None, None),
            ],
        )
        db.executemany(
            "INSERT INTO sections VALUES (?, ?, ?, ?, ?, ?, 0)",
            [
                (A, 1, "budget", "money", 1, 2),
                (A, 2, "minutes", "deliberation", 3, 2),  # given in reverse; page 2 is in two
                (A, 3, "report", "information", 4, 4),  # not searched
                (A, 4, "proposal", "proposals", 6, 9),  # the document ends at page 7
                (BULLETIN, 1, "minutes", "deliberation", 1, 1),
                (PRIVATE, 1, "minutes", "deliberation", 1, 1),
                (D, 1, "decisions", "deliberation", 1, 1),
            ],
        )
        db.commit()
    return path


def text_db(path):
    """text.db with a text layer pass and an OCR run. Page 1 of A has both; page 7 has neither."""
    pages = [
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


@pytest.mark.parametrize(
    ("text", "joined"),
    [
        ("Gemeinde-\nrat", "Gemeinderat"),
        ("Ver-\nwal-\ntung", "Verwaltung"),
        ("Abstim-\nmung über die Vor-\nlage", "Abstimmung über die Vorlage"),
        ("Gebüh-\nren und Ä-\nnderung", "Gebühren und Änderung"),
        ("crédit d'enga-\ngement", "crédit d'engagement"),
        ("é-\nécole", "éécole"),
        # an upper-case continuation is a new word: a compound or a name
        ("Gemeinde-\nRat", "Gemeinde-\nRat"),
        ("Gemeinde-\nÄmter", "Gemeinde-\nÄmter"),
        # no letter on either side, or not exactly a hyphen and one line break
        ("2025-\n2026", "2025-\n2026"),
        ("Budget-\n2026", "Budget-\n2026"),
        ("Seite 3 -\nweiter", "Seite 3 -\nweiter"),
        ("-\nrat", "-\nrat"),
        ("Gemeinde-\n", "Gemeinde-\n"),
        ("Gemeinde- \nrat", "Gemeinde- \nrat"),
        ("Gemeinde-\n\nrat", "Gemeinde-\n\nrat"),
        ("Gemeinde–\nrat", "Gemeinde–\nrat"),
        ("Gemeinde-rat", "Gemeinde-rat"),
        # a hyphen before und, oder, bis, bzw or sowie shortens a compound
        ("Ein-\nund Ausgaben", "Ein-\nund Ausgaben"),
        ("Hoch-\noder Tiefbau", "Hoch-\noder Tiefbau"),
        ("Primar-\nbzw. Sekundarschule", "Primar-\nbzw. Sekundarschule"),
        ("Gemeinde-\nunderlage", "Gemeindeunderlage"),
    ],
)
def test_words_split_at_a_line_end_are_joined(text, joined):
    assert fulltext.join_split_words(text) == joined


def test_the_types_are_those_of_deliberation_money_and_proposals():
    families = {"deliberation", "money", "proposals"}
    assert set(fulltext.TYPES) == {t for t, f in build.FAMILIES.items() if f in families}


def test_the_index_holds_each_page_in_scope_once(tmp_path):
    serving = serving_db(tmp_path / "serving.db")
    text = text_db(tmp_path / "text.db")
    out = tmp_path / "fulltext.db"

    counts = fulltext.run(out, serving, text)
    assert counts["documents"] == 2
    assert counts["pages"] == {"in_sections": 6, "no_text": 1, "too_short": 1, "indexed": 4}
    types = counts["section_types"]
    assert types["budget"] == {"pages": 2, "indexed": 2}
    assert types["minutes"] == {"pages": 2, "indexed": 1}
    assert types["proposal"] == {"pages": 2, "indexed": 1}
    assert types["decisions"] == {"pages": 1, "indexed": 1}
    assert types["accounts"] == {"pages": 0, "indexed": 0}
    assert fulltext.run(out, serving, text) == counts  # a rebuild replaces, never appends
    assert not (tmp_path / "fulltext.db.tmp").exists()

    db = sqlite3.connect(out)
    assert db.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    assert db.execute("SELECT sha256, page, source, run FROM pages ORDER BY id").fetchall() == [
        (A, 1, "ocr", "ocr:q"),
        (A, 2, "layer", "layer:d"),
        (A, 6, "layer", "layer:d"),
        (D, 1, "layer", "layer:d"),
    ]

    def found(query):
        return db.execute(
            "SELECT p.sha256, p.page FROM page_fts f JOIN pages p ON p.id = f.rowid "
            "WHERE page_fts MATCH ? ORDER BY rank",
            (query,),
        ).fetchall()

    assert found("gemeinderat") == found("rat") == [(A, 2)]
    assert found('"credit d\'engagement"') == found("CRÉDIT") == [(A, 1)]
    assert found("tempo* 30") == [(A, 6)]
    assert found("zwischentext") == []  # the OCR answer counts, not the text layer
    assert found("kredit") == []  # outside the sections, a bulletin, a private body
    assert db.execute("SELECT text FROM page_fts WHERE rowid = 2").fetchone() == (
        "Der Gemeinderat beschliesst den Steuerfuss.\nGemeinde-\nRat",
    )

    record = dict(db.execute("SELECT key, value FROM build"))
    for name in ("serving", "text"):
        path = tmp_path / f"{name}.db"
        assert record[f"{name}_db_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert json.loads(record["pages"]) == counts["pages"]
    assert json.loads(record["section_types"]) == counts["section_types"]
    assert record["rules"] == fulltext.RULES and "fewer than 20 non-space" in record["rules"]
    db.close()

    # a build that fails leaves the index as it was
    broken = tmp_path / "broken.db"
    sqlite3.connect(broken).close()
    with pytest.raises(sqlite3.OperationalError, match="page_text"):
        fulltext.run(out, serving, broken)
    assert not (tmp_path / "fulltext.db.tmp").exists()
    with closing(sqlite3.connect(out)) as db:
        assert db.execute("SELECT count(*) FROM pages").fetchone() == (4,)


def test_build_fulltext_writes_into_the_data_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    serving_db(tmp_path / "serving.db")
    text_db(tmp_path / "text.db")
    result = CliRunner().invoke(app, ["build-fulltext"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout.splitlines()[-1])["pages"]["indexed"] == 4
    assert settings.fulltext_db.exists()
