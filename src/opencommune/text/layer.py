"""The PDF's own text layer, read with PyMuPDF, on every page of chosen section types.

`section_pages` lists the pages: every page of a section of the given types and `margin` pages on
either side, within the document. `measure` reads them, one process per document, and writes one
JSON line per page:

- `sha256`, `page`;
- `sections`: the section types whose pages, widened by the margin, include this one;
- `chars`: non-space characters of the text layer;
- `odd`: of those, U+FFFD and private-use, unassigned or control characters;
- `alnum`: of those, letters and digits;
- `image_cover`: the share of the page the largest image covers;
- `text`: `page.get_text()`, in the PDF's order.

A document that cannot be read gets one line with `error`. This module only measures; `queue`
chooses the pages for OCR from these lines.
"""

from __future__ import annotations

import json
import logging
import multiprocessing
import sqlite3
import time
import unicodedata
from collections import defaultdict
from collections.abc import Sequence
from contextlib import closing
from pathlib import Path

import pymupdf

log = logging.getLogger(__name__)

ODD_CATEGORIES = ("Co", "Cn", "Cc")


def section_pages(
    serving_db: Path, types: Sequence[str], margin: int
) -> dict[str, dict[int, list[str]]]:
    """sha256 -> page -> the section types whose pages, widened by `margin`, include it."""
    found: dict[str, dict[int, set[str]]] = defaultdict(lambda: defaultdict(set))
    marks = ",".join("?" * len(types))
    with closing(sqlite3.connect(f"file:{serving_db}?mode=ro", uri=True)) as db:
        rows = db.execute(
            "select s.sha256, s.type, s.first_page, s.last_page, d.page_count from sections s "
            f"join documents d using (sha256) where s.type in ({marks})",
            list(types),
        ).fetchall()
    for sha, kind, first, last, count in rows:
        for page in range(max(1, first - margin), min(count, last + margin) + 1):
            found[sha][page].add(kind)
    return {sha: {p: sorted(k) for p, k in pages.items()} for sha, pages in found.items()}


def read_page(page: pymupdf.Page, sha: str, number: int, sections: list[str]) -> dict:
    text = page.get_text()
    chars = [c for c in text if not c.isspace()]
    area = abs(page.rect) or 1.0
    cover = 0.0
    for info in page.get_image_info():
        box = pymupdf.Rect(info["bbox"]) & page.rect
        cover = max(cover, abs(box) / area)
    return {
        "sha256": sha,
        "page": number,
        "sections": sections,
        "chars": len(chars),
        "odd": sum(1 for c in chars if c == "�" or unicodedata.category(c) in ODD_CATEGORIES),
        "alnum": sum(1 for c in chars if c.isalnum()),
        "image_cover": round(cover, 3),
        "text": text,
    }


def read_document(job: tuple[str, str, list[tuple[int, list[str]]]]) -> list[dict]:
    path, sha, pages = job
    pymupdf.TOOLS.mupdf_display_errors(False)
    try:
        with pymupdf.open(path) as doc:
            return [read_page(doc[number - 1], sha, number, kinds) for number, kinds in pages]
    except Exception as error:  # noqa: BLE001 - recorded per document
        return [{"sha256": sha, "error": f"{type(error).__name__}: {error}"}]


def written(out: Path) -> tuple[dict[str, set[int]], set[str]]:
    """Pages already in `out` per document, and the documents recorded as unreadable."""
    pages: dict[str, set[int]] = defaultdict(set)
    failed: set[str] = set()
    if out.exists():
        with out.open() as lines:
            for line in lines:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:  # a line cut off when a run stopped
                    continue
                if "error" in record:
                    failed.add(record["sha256"])
                else:
                    pages[record["sha256"]].add(record["page"])
    return pages, failed


def measure(
    pages: dict[str, dict[int, list[str]]], raw: Path, out: Path, workers: int
) -> dict[str, int]:
    """Append the lines of the documents not yet complete in `out`. A document a stopped run left
    incomplete is read again, so some of its pages then appear twice, with the same values."""
    done, failed = written(out)
    jobs = [
        (str(raw / f"{sha}.pdf"), sha, sorted(by_page.items()))
        for sha, by_page in sorted(pages.items())
        if sha not in failed and not set(by_page) <= done.get(sha, set())
    ]
    total = sum(len(job[2]) for job in jobs)
    log.info(
        "%d documents, %d pages to read; %d documents done before",
        len(jobs),
        total,
        len(pages) - len(jobs),
    )
    counts = {"documents": len(jobs), "pages": 0, "unreadable": 0}
    started = last = time.monotonic()
    # spawn, not fork: a fork of a process that runs threads can deadlock
    context = multiprocessing.get_context("spawn")
    with out.open("a") as sink, context.Pool(workers, maxtasksperchild=200) as pool:
        for records in pool.imap_unordered(read_document, jobs, chunksize=4):
            # one write per document: a stop cuts at most the last line
            sink.write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))
            if "error" in records[0]:
                counts["unreadable"] += 1
            else:
                counts["pages"] += len(records)
            if time.monotonic() - last > 300:
                last = time.monotonic()
                log.info(
                    "%d of %d pages, %.0f pages/s",
                    counts["pages"],
                    total,
                    counts["pages"] / (last - started),
                )
    return counts
