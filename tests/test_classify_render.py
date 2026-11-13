import hashlib
import json
import os
import signal
import time

import pymupdf
import pytest

from opencommune.classify import record
from opencommune.classify.render import Rendered, document_request, pages_to_send, render_all

ROW = {"sha256": "ab" * 32, "canton": "ZH", "commune_name": "Musterdorf"}
# The request the first implementation built for the PDF below with classify-65e415a748e2 and
# PyMuPDF 1.28.2. A change to the request layout, or another PyMuPDF, changes it: answers are only
# comparable within one prompt version when its requests are the same bytes.
FIRST_IMPLEMENTATION_SHA256 = "9107826020ddb5e45e12edead8adde1f923c5c1969f27fe796ba86ec8266ed70"


def sample_pdf(path):
    doc = pymupdf.open()
    pages = [
        (595, 842, "Einladung zur Gemeindeversammlung"),
        (842, 595, "Budget 2027"),
        (2384, 3370, "Zonenplan"),  # A0: scaled down to the patch limit
    ]
    for width, height, text in pages:
        page = doc.new_page(width=width, height=height)
        page.insert_text((72, 72), text, fontsize=24)
        page.draw_rect(pymupdf.Rect(72, 100, width - 72, height - 72), color=(0, 0, 0))
    doc.save(path)
    return path


def test_requests_are_the_bytes_the_first_implementation_sent(tmp_path):
    rendered = document_request(
        ROW, sample_pdf(tmp_path / "a.pdf"), record.load(record.DEFAULT_VERSION)
    )
    assert hashlib.sha256(rendered.line.encode()).hexdigest() == FIRST_IMPLEMENTATION_SHA256
    assert (rendered.pages, rendered.pages_sent, rendered.jpeg_quality) == (3, 3, 75)
    body = json.loads(rendered.line)["body"]
    assert body["store"] is False and body["model"] == "gpt-6-luna"


def test_an_empty_file_is_unreadable(tmp_path):
    (tmp_path / "x.pdf").write_bytes(b"")
    assert document_request(ROW, tmp_path / "x.pdf", record.load(record.DEFAULT_VERSION)) is None


def test_long_documents_send_the_start_the_end_and_pages_between():
    assert pages_to_send(5, 150) == [0, 1, 2, 3, 4]
    chosen = pages_to_send(600, 150)
    assert len(chosen) == 150 and chosen == sorted(set(chosen))
    assert chosen[:50] == list(range(50)) and chosen[-25:] == list(range(575, 600))


def work(row):
    name = row["sha256"]
    if name == "crash":
        os.kill(os.getpid(), signal.SIGKILL)
    if name == "hang":
        time.sleep(60)
    if name == "unreadable":
        return None
    if name == "hog":
        blocks = []
        while True:
            blocks.append(bytearray(50_000_000))
    return Rendered("line", 1, 1, 75, 5)


def run(tmp_path, names, **options):
    seen = {}
    render_all(
        [{"sha256": n} for n in names],
        work,
        tmp_path,
        workers=2,
        on_done=lambda row, result, problem: seen.__setitem__(row["sha256"], (result, problem)),
        **options,
    )
    return seen


def test_a_crash_or_a_hang_costs_only_that_document(tmp_path):
    seen = run(tmp_path, ["ok1", "crash", "hang", "unreadable", "ok2"], timeout=1.0)
    assert seen["ok1"] == (Rendered("line", 1, 1, 75, 5), None)
    assert seen["ok2"][1] is None
    assert seen["crash"] == (None, "crashed, exit code -9")
    assert seen["hang"] == (None, "timed out")
    assert seen["unreadable"] == (None, "unreadable")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.skipif(not os.path.exists("/proc/self/oom_score_adj"), reason="Linux only")
def test_a_document_that_takes_too_much_memory_fails_alone(tmp_path):
    seen = run(tmp_path, ["hog", "ok1"], timeout=30.0, memory=500_000_000)
    assert seen["ok1"][1] is None
    assert seen["hog"][0] is None and seen["hog"][1].startswith("crashed")
