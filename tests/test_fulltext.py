import hashlib
import json
import sqlite3
from contextlib import closing

import pytest
from typer.testing import CliRunner

from opencommune import fulltext
from opencommune.cli import app
from opencommune.config import settings
from tests.scope_data import A, D, serving_db, text_db


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
