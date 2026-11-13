"""Classification jobs: render requests, send them as batches, store the answers.

`prepare` renders what the catalogue holds and has no answer for the prompt version yet, so the
first run, a retry and next month's new documents are the same step. `drive` sends the rendered
files, stores what comes back, and stops sending when answers are poor, a batch fails or the cost
passes the limit. A document is never sent again once it has an answer; one that keeps failing
stops after MAX_FAILURES failures.
"""

from __future__ import annotations

import fcntl
import gzip
import json
import logging
import re
import shutil
import sqlite3
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial
from pathlib import Path

import httpx

from . import record as records
from .batch_api import FINISHED, BatchAPI, cost, input_name, parse_line
from .record import PromptRecord
from .render import Rendered, document_request, render_all
from .store import Store

log = logging.getLogger(__name__)

MAX_FAILURES = 3
RENDER_TIMEOUT = 900  # seconds for one document
RENDER_STOP_AFTER, RENDER_STOP_SHARE = 200, 0.10  # this many failing means the machine, not PDFs
MISSING_STOP_SHARE = 0.01  # more missing PDFs than this means the disk, not the catalogue
MAX_FILE_BYTES = 180_000_000  # the Batch API takes input files of up to 200 MB
QUEUE_TOKENS = 14_000_000_000  # enqueued tokens the account may have in flight for the model
UPLOADS = 6  # at once
SEND_ROUND = 240  # files sent before the results are looked at again
MIN_OUTCOMES = 200  # fewer say too little to stop on answer quality or on a projection
USABLE_SHARE = 0.95
POLL_SECONDS = 300
# Planning figures for the expected cost, measured on 215,530 answers of classify-65e415a748e2:
# each page label adds about 12 input tokens and an answer has 511 output tokens on average.
LABEL_TOKENS, ANSWER_TOKENS = 12, 511
JOB_NAME = re.compile(r"[a-z0-9][a-z0-9-]*")


@dataclass(frozen=True)
class Paths:
    """Where a job's files live: the database and archived results in DATA_DIR, rendered requests
    on scratch, because they are large, can be rendered again and hold page images."""

    database: Path
    outputs: Path
    scratch: Path

    def inputs(self, job: str) -> Path:
        folder = self.scratch / "classify" / job
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        return folder


def open_documents(
    catalogue: list[dict], store: Store, version: str, max_failures: int = MAX_FAILURES
) -> list[dict]:
    """Catalogue rows that still need a request for the version."""
    answered = store.answered(version)
    failures = store.failure_counts(version)
    return [
        row
        for row in catalogue
        if row["sha256"] not in answered and failures[row["sha256"]] < max_failures
    ]


def read_catalogue(database: Path, cantons: set[str] | None, shas: set[str] | None) -> list[dict]:
    db = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        query = "SELECT sha256, canton, commune_name FROM pdf_catalog ORDER BY sha256"
        rows = [
            {"sha256": sha, "canton": canton, "commune_name": name}
            for sha, canton, name in db.execute(query)
        ]
    finally:
        db.close()
    return [
        r
        for r in rows
        if (cantons is None or r["canton"] in cantons) and (shas is None or r["sha256"] in shas)
    ]


def present(rows: list[dict], raw: Path) -> list[dict]:
    """Rows whose PDF is on disk. A missing PDF stays open with no failure held against it; many
    missing means the disk is not mounted, and nothing is prepared."""
    found = [r for r in rows if (raw / f"{r['sha256']}.pdf").exists()]
    missing = len(rows) - len(found)
    if missing > max(10, MISSING_STOP_SHARE * len(rows)):
        raise RuntimeError(f"{missing} of {len(rows)} PDFs are missing from {raw}")
    if missing:
        log.warning("%d PDFs are missing and stay open", missing)
    return found


@contextmanager
def exclusive(paths: Paths, version: str) -> Iterator[None]:
    """One prepare or drive per prompt version at a time: two could pay for the same documents."""
    lock = paths.database.parent / f"{version}.lock"
    with lock.open("w") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError(f"another prepare or drive is running for {version}") from None
        yield


def drop_unlisted_lines(path: Path, listed: set[str]) -> None:
    """A crash can leave the last input file with a cut line, or a line whose request was never
    stored. Either would make the batch fail or pay twice."""
    keep: list[bytes] = []
    with path.open("rb") as stream:
        for line in stream:
            found = re.match(rb'\{"custom_id": "([0-9a-f]+)"', line)
            if line.endswith(b"\n") and found and found.group(1).decode() in listed:
                keep.append(line)
    if not keep:
        path.unlink()
    elif len(b"".join(keep)) != path.stat().st_size:
        trimmed = path.with_suffix(".trim")
        trimmed.write_bytes(b"".join(keep))
        trimmed.rename(path)


def prepare(
    store: Store,
    paths: Paths,
    record: PromptRecord,
    job: str,
    rows: list[dict],
    raw: Path,
    workers: int,
    work: Callable[[dict], Rendered | None] | None = None,
) -> dict[str, int]:
    """Render the open documents among `rows` into input files for `job`."""
    if not JOB_NAME.fullmatch(job):
        raise ValueError("a job name is lower-case letters, digits and hyphens")
    version = record.version
    unfinished = [j for j in store.open_jobs(version) if j != job]
    if unfinished:
        raise RuntimeError(f"finish {', '.join(unfinished)} with drive first")
    store.add_job(job, version)
    inputs = paths.inputs(job)
    requested = store.requested(job)
    existing = sorted(inputs.glob("input-*.jsonl"))
    if existing:
        drop_unlisted_lines(existing[-1], requested)
    todo = [r for r in open_documents(rows, store, version) if r["sha256"] not in requested]
    todo = present(todo, raw)
    log.info("job %s, prompt %s: %d documents to render", job, version, len(todo))
    work = work or partial(_render, raw=raw, record=record)
    on_disk = (int(p.stem.removeprefix("input-")) for p in inputs.glob("input-*.jsonl"))
    numbers = [*store.file_sizes(job), *on_disk]
    output = _InputFiles(inputs, max(numbers, default=0))
    counts = {"rendered": 0, "failed": 0}
    rendering = inputs / "rendering"
    shutil.rmtree(rendering, ignore_errors=True)
    rendering.mkdir()

    def on_done(row: dict, result: Rendered | None, problem: str | None) -> None:
        if result is None:
            counts["failed"] += 1
            store.add_failure(row["sha256"], version, job, "render", problem or "unreadable")
            done = counts["rendered"] + counts["failed"]
            if done >= RENDER_STOP_AFTER and counts["failed"] / done > RENDER_STOP_SHARE:
                raise RuntimeError(f"{counts['failed']} of {done} documents did not render")
            return
        file = output.write(result.line)
        store.add_request(job, row["sha256"], file, result)
        counts["rendered"] += 1
        if counts["rendered"] % 1000 == 0:
            log.info("rendered %d of %d", counts["rendered"], len(todo))

    try:
        render_all(todo, work, rendering, workers, RENDER_TIMEOUT, on_done)
    finally:
        output.close()
        shutil.rmtree(rendering, ignore_errors=True)
    return counts


def _render(row: dict, raw: Path, record: PromptRecord) -> Rendered | None:
    return document_request(row, raw / f"{row['sha256']}.pdf", record)


class _InputFiles:
    """Numbered input files under the size limit. Each line is on disk before its request is
    stored, so a crash leaves at most lines that drop_unlisted_lines removes."""

    def __init__(self, folder: Path, last: int) -> None:
        self.folder, self.number, self.size, self.stream = folder, last, 0, None

    def write(self, line: str) -> int:
        encoded = line.encode() + b"\n"
        if self.stream is None or self.size + len(encoded) > MAX_FILE_BYTES:
            self.close()
            self.number += 1
            self.size = 0
            self.stream = (self.folder / input_name(self.number)).open("xb")
        self.stream.write(encoded)
        self.stream.flush()
        self.size += len(encoded)
        return self.number

    def close(self) -> None:
        if self.stream:
            self.stream.close()
            self.stream = None


def expected_usd(store: Store, record: PromptRecord, job: str) -> float:
    prompt_tokens = len(record.prompt) // 4
    total = 0.0
    for requests, pages, tokens in store.file_sizes(job).values():
        input_tokens = tokens + requests * prompt_tokens + pages * LABEL_TOKENS
        total += cost(record.settings.model, input_tokens, requests * ANSWER_TOKENS)
    return total


def decide(
    spent: float, projected: float, good: int, seen: int, limit: float, batch_failed: bool
) -> str | None:
    """Why to send no more, if there is a reason."""
    if spent >= limit:
        return "the money spent reached the limit"
    if batch_failed:
        return "a batch failed"
    if seen < MIN_OUTCOMES:
        return None
    if good / seen < USABLE_SHARE:
        return f"under {USABLE_SHARE:.0%} of answers are usable"
    if projected > limit:
        return "the projected cost is above the limit"
    return None


def store_results(store: Store, api: BatchAPI, paths: Paths, job: str, batch: dict) -> bool:
    """Keep a finished batch's raw results, store them in one transaction, then delete its files
    at OpenAI. True if the batch failed as a whole."""
    version = store.job_version(job)
    lines = api.result_lines(batch)
    paths.outputs.mkdir(mode=0o700, parents=True, exist_ok=True)
    archive = paths.outputs / f"{batch['id']}.jsonl.gz"
    with gzip.open(archive, "wt") as stream:
        stream.writelines(line + "\n" for line in lines)
    archive.chmod(0o600)
    with store.transaction():
        for line in lines:
            outcome = parse_line(line)
            request = store.request(job, outcome.sha256)
            if outcome.answer is not None:
                store.add_answer(
                    outcome.sha256,
                    version,
                    job,
                    outcome.answer,
                    outcome.usage,
                    model=outcome.model,
                    **request,
                )
            else:
                store.add_failure(
                    outcome.sha256,
                    version,
                    job,
                    "request",
                    outcome.reason or "no answer",
                    outcome.detail,
                    outcome.usage,
                )
        store.mark(batch["id"], "fetched_at")
    api.delete_files(batch)
    store.mark(batch["id"], "cleaned_at")
    if batch["status"] == "failed":
        log.error("batch %s failed: %s", batch["id"], batch.get("errors"))
    return batch["status"] == "failed"


def drive(
    store: Store,
    api: BatchAPI,
    paths: Paths,
    record: PromptRecord,
    job: str,
    max_usd: float,
    poll: float = POLL_SECONDS,
) -> None:
    """Send the job's input files, store the results as they come, until all are back."""
    version = record.version
    if store.job_version(job) != version:
        raise ValueError(f"job {job} does not belong to {version}")
    inputs = paths.inputs(job)
    sizes = store.file_sizes(job)
    tokens = {file: size[2] for file, size in sizes.items()}
    expected = expected_usd(store, record, job)
    log.info("job %s: %d files, expected USD %.2f", job, len(sizes), expected)
    if expected > max_usd:
        raise RuntimeError(f"the expected cost of USD {expected:.2f} is above the limit")
    sent = store.batches(job)
    missing = [f for f in sizes if f not in sent and not (inputs / input_name(f)).exists()]
    if missing:
        raise RuntimeError(f"{len(missing)} unsent input files are missing from {inputs}")
    stop: str | None = None
    batch_failed = cancelled = False
    look_for_lost = True
    while True:
        try:
            if look_for_lost:
                known = store.batches(job)
                for file, batch_id in api.find(job).items():
                    if file not in known:
                        store.add_batch(job, file, batch_id)
                        log.warning("%s was sent before and is followed again", input_name(file))
                look_for_lost = False
            for batch in store.batches(job).values():
                if batch.fetched and not batch.cleaned:
                    api.delete_files(api.get(batch.batch_id))
                    store.mark(batch.batch_id, "cleaned_at")
                elif not batch.fetched:
                    state = api.get(batch.batch_id)
                    if state["status"] in FINISHED:
                        batch_failed |= store_results(store, api, paths, job, state)
            batches = store.batches(job)
            for file, batch in batches.items():
                if batch.fetched:
                    (inputs / input_name(file)).unlink(missing_ok=True)
            spent = cost(record.settings.model, *store.usage(version, job))
            done = sum(tokens.get(f, 0) for f, b in batches.items() if b.fetched)
            projected = spent / done * sum(tokens.values()) if done else 0.0
            good, seen = store.outcome_counts(version, job)
            fetched = sum(b.fetched for b in batches.values())
            log.info(
                "batches %d of %d back, %d of %d answers usable, USD %.2f spent, %.2f projected",
                fetched,
                len(batches),
                good,
                seen,
                spent,
                projected,
            )
            reason = decide(spent, projected, good, seen, max_usd, batch_failed)
            if reason and not stop:
                stop = reason
                log.warning("sending no more: %s; what is out is still fetched", reason)
            if spent >= max_usd and not cancelled:
                for batch in batches.values():
                    if not batch.fetched:
                        api.cancel(batch.batch_id)
                cancelled = True
            unsent = [f for f in sorted(sizes) if f not in batches]
            if fetched == len(batches) and (stop or not unsent):
                log.info("all results are in; open documents join the next prepare")
                return
            in_flight = sum(tokens[f] for f, b in batches.items() if not b.fetched)
            chosen: list[int] = []
            for file in [] if stop else unsent[:SEND_ROUND]:
                if in_flight + tokens[file] > QUEUE_TOKENS and (chosen or in_flight):
                    break
                chosen.append(file)
                in_flight += tokens[file]
            with ThreadPoolExecutor(max_workers=UPLOADS) as pool:
                futures = {pool.submit(api.send, inputs / input_name(f), job, f): f for f in chosen}
                for future in as_completed(futures):
                    store.add_batch(job, futures[future], future.result())
            if chosen:
                log.info("sent %d files", len(chosen))
                continue
        except (httpx.HTTPError, ValueError, KeyError) as error:
            log.warning("retrying after %s: %s", type(error).__name__, error)
            look_for_lost = True
        time.sleep(poll)


def import_ledger(store: Store, ledger: Path, frozen: Path | None = None) -> dict[str, int]:
    """Copy the answers and failures of a ledger written by the first implementation (one JSON
    object per line) into the store. The ledger is only read; importing again adds nothing."""
    counts = {"answers": 0, "failures": 0, "already there": 0}
    known = set(records.versions())
    with store.transaction():
        if frozen is not None:
            state = json.loads(frozen.read_text())
            store.freeze_renderer(state["prompt_version"], f"pymupdf {state['pymupdf']}")
        with ledger.open() as stream:
            for line in stream:
                row = json.loads(line)
                version = row["prompt_version"]
                if version not in known:
                    raise ValueError(f"the ledger names {version}, which has no prompt record")
                old = row.get("usage") or {}
                usage = {
                    "input_tokens": old.get("prompt_tokens"),
                    "output_tokens": old.get("completion_tokens"),
                    "output_tokens_details": old.get("completion_tokens_details") or {},
                }
                if row["status"] == "answered":
                    added = store.add_answer(
                        row["sha256"],
                        version,
                        row["job"],
                        row["answer"],
                        usage,
                        model=row.get("model_returned"),
                        pages=row.get("pages"),
                        pages_sent=row.get("pages_sent"),
                        jpeg_quality=row.get("jpeg_quality"),
                        at=row["at"],
                    )
                    kind = "answers"
                else:
                    error = row.get("error")
                    if isinstance(error, dict):
                        reason = error.get("code") or error.get("message")
                    else:
                        reason = error
                    added = store.add_failure(
                        row["sha256"],
                        version,
                        row["job"],
                        "render" if row.get("stage") == "render" else "request",
                        str(reason or row["status"]),
                        error,
                        usage,
                        at=row["at"],
                    )
                    kind = "failures"
                counts[kind if added else "already there"] += 1
    return counts


def status(store: Store, version: str) -> dict:
    answered = store.answered(version)
    failures = store.failure_counts(version)
    model = records.load(version).settings.model
    return {
        "answered": len(answered),
        "failing": len(failures),
        "given up": sum(n >= MAX_FAILURES for n in failures.values()),
        "open jobs": store.open_jobs(version),
        "usd": round(cost(model, *store.usage(version)), 2),
    }
