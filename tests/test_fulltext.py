import hashlib
import json
import sqlite3
from contextlib import closing

import pytest
from typer.testing import CliRunner

from opencommune import fulltext
from opencommune.cli import app
from opencommune.config import settings
from opencommune.privacy import redact
from tests.scope_data import A, D, privacy_db, serving_db, text_db


def found_in(text):
    """A privacy check that finds the street and the number of the decision."""
    spans = []
    for label, words in (("private_address", "Hauptstrasse"), ("private_date", "123/2026")):
        start = text.find(words)
        if start >= 0:
            spans.append([label, start, start + len(words), 0.9])
    return spans


def test_the_index_holds_each_page_in_scope_once_redacted(tmp_path):
    serving = serving_db(tmp_path / "serving.db")
    text = text_db(tmp_path / "text.db")
    privacy = privacy_db(tmp_path / "privacy.db", serving, text, found_in)
    out = tmp_path / "fulltext.db"

    counts = fulltext.run(out, serving, text, privacy)
    assert counts["documents"] == 2
    assert counts["pages"] == {
        "in_sections": 6,
        "no_text": 1,
        "too_short": 1,
        "not_checked": 0,
        "indexed": 4,
    }
    assert counts["marks"] == {"private_address": 1}
    types = counts["section_types"]
    assert types["budget"] == {"pages": 2, "indexed": 2}
    assert types["minutes"] == {"pages": 2, "indexed": 1}
    assert types["proposal"] == {"pages": 2, "indexed": 1}
    assert types["decisions"] == {"pages": 1, "indexed": 1}
    assert types["accounts"] == {"pages": 0, "indexed": 0}
    assert fulltext.run(out, serving, text, privacy) == counts  # a rebuild replaces, never appends
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
    assert found("hauptstrasse") == found("address") == []  # the mark is not a word of the page
    assert found("2026") == [(D, 1)]  # dates are kept
    assert found("zwischentext") == []  # the OCR answer counts, not the text layer
    assert found("kredit") == []  # outside the sections, a bulletin, a private body
    assert db.execute("SELECT text FROM page_fts WHERE rowid = 2").fetchone() == (
        "Der Gemeinderat beschliesst den Steuerfuss.\nGemeinde-\nRat",
    )
    assert db.execute("SELECT text FROM page_fts WHERE rowid = 3").fetchone() == (
        "Antrag Tempo 30 auf der \uff3baddress\uff3d",
    )

    record = dict(db.execute("SELECT key, value FROM build"))
    for name in ("serving", "text", "privacy"):
        path = tmp_path / f"{name}.db"
        assert record[f"{name}_db_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert json.loads(record["pages"]) == counts["pages"]
    assert json.loads(record["section_types"]) == counts["section_types"]
    assert record["rules"] == fulltext.RULES and "fewer than 20 non-space" in record["rules"]
    assert "private_person by \uff3bname\uff3d" in record["rules"]
    assert f"tokenchars '{redact.OPEN}{redact.CLOSE}'" in fulltext.SCHEMA
    db.close()

    # a build that fails leaves the index as it was
    broken = tmp_path / "broken.db"
    sqlite3.connect(broken).close()
    with pytest.raises(sqlite3.OperationalError, match="page_text"):
        fulltext.run(out, serving, broken, privacy)
    assert not (tmp_path / "fulltext.db.tmp").exists()
    with closing(sqlite3.connect(out)) as db:
        assert db.execute("SELECT count(*) FROM pages").fetchone() == (4,)


def test_a_page_is_left_out_until_the_privacy_check_has_read_its_text(tmp_path):
    serving = serving_db(tmp_path / "serving.db")
    text = text_db(tmp_path / "text.db")
    privacy = privacy_db(tmp_path / "privacy.db", serving, text)
    with closing(sqlite3.connect(privacy)) as db, db:
        db.execute("DELETE FROM findings WHERE sha256 = ? AND page = 1", (A,))  # never checked
        db.execute(
            "UPDATE findings SET text_sha256 = ? WHERE page = 2", ("0" * 64,)
        )  # text changed
    out = tmp_path / "fulltext.db"
    counts = fulltext.run(out, serving, text, privacy)
    assert (counts["pages"]["not_checked"], counts["pages"]["indexed"]) == (2, 2)
    with closing(sqlite3.connect(out)) as db:
        assert db.execute("SELECT sha256, page FROM pages").fetchall() == [(A, 6), (D, 1)]


def test_build_fulltext_writes_into_the_data_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    serving = serving_db(tmp_path / "serving.db")
    text = text_db(tmp_path / "text.db")
    assert CliRunner().invoke(app, ["build-fulltext"]).exit_code != 0  # no privacy.db yet
    privacy_db(tmp_path / "privacy.db", serving, text)
    result = CliRunner().invoke(app, ["build-fulltext"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout.splitlines()[-1])["pages"]["indexed"] == 4
    assert settings.fulltext_db.exists()
