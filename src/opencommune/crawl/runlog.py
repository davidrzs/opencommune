"""Append-only log of fetch runs: data/logs/fetch_runs.jsonl, one line per commune, source and run.

A line carries when the crawl started and how long it took, the request count, the listing status
(ok, empty, or the error kind of the entry pages), how many documents were listed, considered, new
and known, every error with its kind, and every document link seen on the last hop with url, date
and title, so a later stage can tell "listed but not held" without crawling again. Dry runs are
marked and left out of last_runs() unless asked for."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path

from ..config import settings

log = logging.getLogger(__name__)

LOG_FILE = "fetch_runs.jsonl"

RunKey = tuple[int, str, str]  # commune_bfs_id, adapter, listing_url


def log_path() -> Path:
    return settings.logs_dir / LOG_FILE


def append(line: dict) -> None:
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    with log_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")


def read_runs() -> Iterator[dict]:
    """Every line in file order; a line cut short by a crash is skipped."""
    path = log_path()
    if not path.exists():
        return
    with path.open(encoding="utf-8") as f:
        for n, raw in enumerate(f, 1):
            if not raw.strip():
                continue
            try:
                yield json.loads(raw)
            except ValueError:
                log.warning("%s line %d is not JSON and was skipped", path, n)


def key(line: dict) -> RunKey:
    return (line["commune_bfs_id"], line["adapter"], line["listing_url"])


def last_runs(include_dry: bool = False) -> dict[RunKey, dict]:
    """The newest line per (commune_bfs_id, adapter, listing_url)."""
    out: dict[RunKey, dict] = {}
    for line in read_runs():
        if include_dry or not line.get("dry_run"):
            out[key(line)] = line
    return out
