import hashlib
import json
import sqlite3
import time
import tomllib
from collections import namedtuple
from contextlib import closing
from pathlib import Path

import pytest
from typer.testing import CliRunner

from opencommune.cli import app
from opencommune.config import settings
from opencommune.privacy import detect
from opencommune.text.queue import MAX_TRIES, Queue
from tests.scope_data import A, D, serving_db, text_db

Span = namedtuple("Span", "label start end score")


class Names:
    """A stand-in for gheim's detector: it reports the word "Gemeinderat" as a person."""

    def __init__(self):
        self.seen = []

    def detect(self, text):
        self.seen.append(text)
        start = text.find("Gemeinderat")
        return [] if start < 0 else [Span("private_person", start, start + 11, 0.912345)]


class Broken:
    def detect(self, text):
        raise RuntimeError("CUDA error: an illegal memory access was encountered")


def make_queue(tmp_path, monkeypatch, chunk_pages=2):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    serving_db(tmp_path / "serving.db")
    text_db(tmp_path / "text.db")
    made = CliRunner().invoke(app, ["privacy", "queue", "q", "--chunk-pages", str(chunk_pages)])
    assert made.exit_code == 0, made.output
    return Queue(tmp_path / "privacy" / "queues" / "q")


def test_the_queue_carries_the_pages_with_usable_text_as_the_index_stores_it(tmp_path, monkeypatch):
    queue = make_queue(tmp_path, monkeypatch)
    items = [item for chunk in queue.chunks() for item in queue.items(chunk)]
    assert [(item["sha256"], item["page"]) for item in items] == [(A, 1), (A, 2), (A, 6), (D, 1)]
    assert items[0]["text"] == "Crédit d'engagement pour la route"  # the OCR answer counts
    assert items[1]["text"] == "Der Gemeinderat beschliesst den Steuerfuss.\nGemeinde-\nRat"
    assert (queue.settings["pages"], queue.settings["chunks"]) == (4, 2)
    wanted = detect.detector_settings()
    assert {key: queue.settings[key] for key in wanted} == wanted
    assert CliRunner().invoke(app, ["privacy", "queue", "q"]).exit_code != 0


def test_a_worker_records_the_spans_of_every_page_once(tmp_path, monkeypatch):
    queue = make_queue(tmp_path, monkeypatch)
    names = Names()
    result = detect.run(queue, "one", None, detector=names)
    assert result["stopped"] == "no chunk left"
    assert (result["ok"], result["chunks_finished"]) == (4, 2)
    assert detect.run(queue, "two", None, detector=names)["stopped"] == "no chunk left"
    assert len(names.seen) == 4
    assert all(queue.is_done(chunk) for chunk in queue.chunks())
    answer = next(r for r in queue.answers("00000") if r["page"] == 2)
    assert answer["spans"] == [["private_person", 4, 15, 0.9123]]
    text = queue.items("00000")[1]["text"]
    assert answer["text_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert answer["worker"].startswith("one@")
    assert queue.status()["pages"] == {"total": 4, "answered": 4, "ok": 4}
    worker = json.loads((queue.root / "workers" / "one" / "worker.json").read_text())
    assert worker["ok"] == 4 and worker["source_sha256"]


def test_errors_are_tried_again_and_a_failing_detector_stops_the_worker(tmp_path, monkeypatch):
    monkeypatch.setattr(detect, "MAX_FAILURES_IN_A_ROW", 2)
    queue = make_queue(tmp_path, monkeypatch, chunk_pages=4)
    failed = detect.run(queue, "one", None, detector=Broken())
    assert (failed["stopped"], failed["error"], failed["chunks_released"]) == (detect.FAILED, 2, 1)
    assert not queue.is_done("00000") and not list((queue.root / "claims").iterdir())
    assert queue.status()["pages"] == {"total": 4, "answered": 0, "error_retry": 2}
    assert detect.run(queue, "two", None, detector=Names())["ok"] == 4
    assert queue.is_done("00000")


def test_a_page_that_fails_every_try_is_given_up(tmp_path, monkeypatch):
    queue = make_queue(tmp_path, monkeypatch, chunk_pages=4)
    result = detect.run(queue, "one", None, detector=Broken())
    assert (result["stopped"], result["error"]) == ("no chunk left", 4 * MAX_TRIES)
    assert queue.is_done("00000")
    assert queue.status()["pages"] == {"total": 4, "answered": 4, "error": 4}


def test_a_worker_stops_at_its_time_and_releases_its_chunk(tmp_path, monkeypatch):
    queue = make_queue(tmp_path, monkeypatch)
    result = detect.run(queue, "one", time.time() - 1, detector=Names())
    assert result["stopped"] == "time is up" and "ok" not in result
    assert not queue.is_done("00000") and not list((queue.root / "claims").iterdir())


def test_a_worker_refuses_a_queue_made_for_another_model(tmp_path, monkeypatch):
    queue = make_queue(tmp_path, monkeypatch)
    monkeypatch.setattr(detect, "REVISION", "0" * 40)
    with pytest.raises(RuntimeError, match="made for"):
        detect.run(queue, "one", None, detector=Names())


def test_the_privacy_extra_pins_the_gheim_the_worker_wants():
    pyproject = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    extra = pyproject["project"]["optional-dependencies"]["privacy"]
    assert f"gheim[local]=={detect.GHEIM}" in extra


def test_the_privacy_commands_check_count_and_import(tmp_path, monkeypatch):
    make_queue(tmp_path, monkeypatch)
    runner = CliRunner()

    def run(*args):
        return runner.invoke(app, ["privacy", *args])

    monkeypatch.setattr(detect, "MAX_FAILURES_IN_A_ROW", 1)
    monkeypatch.setattr(detect, "load", lambda: (Broken(), {"gheim": "test"}))
    assert run("detect", "q", "--worker", "1").exit_code == 2
    monkeypatch.setattr(detect, "load", lambda: (Names(), {"gheim": "test"}))
    ran = run("detect", "q", "--worker", "2")
    assert ran.exit_code == 0, ran.output
    assert json.loads(ran.stdout.splitlines()[-1])["ok"] == 4
    assert json.loads(run("status", "q").stdout)["pages"]["ok"] == 4
    assert run("status", "../q").exit_code != 0 and run("detect", "nope").exit_code != 0
    imported = run("import", "q")
    assert imported.exit_code == 0, imported.output
    assert json.loads(imported.stdout) == {"run": "q", "pages": {"ok": 4}}
    assert json.loads(run("import", "q").stdout) == {"run": "q", "pages": {"ok": 4}}
    with closing(sqlite3.connect(settings.privacy_db)) as db:
        spans, detail = db.execute(
            "SELECT spans, detail FROM findings WHERE sha256 = ? AND page = 2", (A,)
        ).fetchone()
        assert json.loads(spans) == [["private_person", 4, 15, 0.9123]]
        assert json.loads(detail)["worker"].startswith("2@")
        assert db.execute("SELECT name, pages FROM runs").fetchall() == [("q", 4)]
