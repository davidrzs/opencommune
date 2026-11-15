"""The privacy check of page text with gheim: which pages (`choose`) and one worker.

`choose` takes the pages in scope (opencommune.scope) with usable text, and the text exactly as the
index stores it, so the offsets found here fit the index.

A worker claims chunks of a privacy queue and runs gheim's calibrated detector on each page: the
gheim-ch-560m model at REVISION with gheim's default O-bias of 0.5, in float32 (the precision of
gheim's published scores). For each page it appends the spans it found, each as [label, start, end,
score] with character offsets into the text, and the SHA-256 of the text it read (UTF-8). A page
whose check raises is recorded as "error" and checked again the next time its chunk is claimed,
by this worker or another, until it has failed queue.MAX_TRIES times.

gheim's regex front end (CompositeDetector) is not used: it marks every full date, Swiss phone
number, email address and URL, most of which are public in council papers. Its other steps, the
replacement of the spans and the repetition of a name found once, are left to the index build.

The worker stops when no chunk is left for it, at `until`, on SIGTERM, or when the detector fails
MAX_FAILURES_IN_A_ROW pages in a row. It releases an unfinished chunk on the way out.
"""

from __future__ import annotations

import hashlib
import json
import logging
import signal
import socket
import time
from collections import Counter
from collections.abc import Iterator
from importlib.metadata import version
from pathlib import Path

from .. import scope
from ..text.queue import Claim, Queue

log = logging.getLogger(__name__)

GHEIM = "0.1.11"  # as pinned by the `privacy` extra in pyproject.toml
MODEL = "joelbarmettler/gheim-ch-560m"
REVISION = "5b2e42e6f479a735ea2bd617297def01cb34edce"
O_BIAS = 0.5  # gheim's default
HEARTBEAT_SECONDS = 60
REPORT_SECONDS = 300
MAX_FAILURES_IN_A_ROW = 25
FAILED = "the detector failed page after page; see the log"
RULE = (
    "pages in scope whose text has at least "
    f"{scope.MIN_CHARS} non-space characters, with the text as the index stores it"
)


def detector_settings() -> dict:
    """How the pages of a queue are checked; the queue records it and its workers follow it."""
    return {
        "detector": "gheim CalibratedDetector",
        "gheim": GHEIM,
        "model": MODEL,
        "revision": REVISION,
        "o_bias": O_BIAS,
        "dtype": "float32",
    }


def choose(serving_db: Path, text_db: Path) -> Iterator[dict]:
    """{"sha256", "page", "text"} for each page to check, by document and page."""
    for page in scope.pages(serving_db, text_db):
        if page.usable:
            yield {"sha256": page.sha256, "page": page.page, "text": page.text}


def load() -> tuple[object, dict]:
    """gheim's calibrated detector over the model at REVISION, on the GPU when there is one, and
    what it runs with. The model comes from the Hugging Face cache, or is downloaded into it."""
    import torch
    from gheim import CalibratedDetector
    from huggingface_hub import snapshot_download

    if version("gheim") != GHEIM:
        raise RuntimeError(f"gheim {version('gheim')} is installed, the check wants {GHEIM}")
    path = snapshot_download(MODEL, revision=REVISION)
    cuda = torch.cuda.is_available()
    detector = CalibratedDetector(
        model_id=path, o_bias=O_BIAS, device="cuda" if cuda else "cpu", dtype=torch.float32
    )
    detector.detect("Der Gemeinderat tagt.")  # loads the weights now, not on the first page
    environment = {
        "gheim": version("gheim"),
        "torch": torch.__version__,
        "transformers": version("transformers"),
        "gpu": torch.cuda.get_device_name(0) if cuda else None,
    }
    return detector, environment


class Worker:
    def __init__(self, queue: Queue, detector, owner: str, until: float | None):
        self.queue, self.detector, self.owner, self.until = queue, detector, owner, until
        self.counts: Counter = Counter()
        self.failures_in_a_row = 0
        self.reason: str | None = None
        self.started = self.last_report = time.monotonic()

    def _halt(self, reason: str) -> None:
        if self.reason is None:
            self.reason = reason
            log.warning("stopping: %s", reason)

    def _check(self, item: dict) -> dict:
        text = item["text"]
        record = {
            "sha256": item["sha256"],
            "page": item["page"],
            "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        }
        started = time.perf_counter()
        try:
            spans = self.detector.detect(text)
        except Exception as error:
            if self.failures_in_a_row == 0:
                log.exception("checking %s page %s failed", item["sha256"], item["page"])
            self.failures_in_a_row += 1
            if self.failures_in_a_row >= MAX_FAILURES_IN_A_ROW:
                self._halt(FAILED)
            return {**record, "status": "error", "error": f"{type(error).__name__}: {error}"}
        self.failures_in_a_row = 0
        return {
            **record,
            "status": "ok",
            "seconds": round(time.perf_counter() - started, 4),
            "spans": [[s.label, s.start, s.end, round(s.score, 4)] for s in spans],
        }

    def _report(self) -> None:
        now = time.monotonic()
        if now - self.last_report >= REPORT_SECONDS:
            self.last_report = now
            seconds = now - self.started
            log.info(
                "%.0f s: %s, %.1f pages/s", seconds, dict(self.counts), self.counts["ok"] / seconds
            )

    def _work(self, claim: Claim) -> None:
        """Check the pages of the chunk that have no final answer yet, then finish or release it."""
        finished = self.queue.finished(claim.chunk)
        items = [
            i for i in self.queue.items(claim.chunk) if (i["sha256"], i["page"]) not in finished
        ]
        log.info(
            "chunk %s: %d pages to check, %d done before", claim.chunk, len(items), len(finished)
        )
        beat = time.monotonic()
        with (self.queue.root / "out" / f"{claim.chunk}.jsonl").open("a") as out:
            for item in items:
                if self.until is not None and time.time() >= self.until:
                    self._halt("time is up")
                if self.reason is not None:
                    break
                if time.monotonic() - beat >= HEARTBEAT_SECONDS:
                    beat = time.monotonic()
                    if not self.queue.touch(claim):
                        log.warning("chunk %s was taken over by another worker", claim.chunk)
                        return
                record = {**self._check(item), "worker": self.owner, "at": round(time.time(), 1)}
                out.write(json.dumps(record, ensure_ascii=False) + "\n")
                out.flush()
                self.counts[record["status"]] += 1
                self._report()
        if set(self.queue.pages(claim.chunk)) <= self.queue.finished(claim.chunk):
            self.queue.finish(claim)
            self.counts["chunks_finished"] += 1
        else:  # stopped, or errors to try again later
            self.queue.release(claim)
            self.counts["chunks_released"] += 1

    def run(self) -> dict:
        previous = signal.signal(signal.SIGTERM, lambda *_: self._halt("SIGTERM"))
        try:
            while self.reason is None:
                claim = self.queue.claim(self.owner)
                if claim is None:
                    self.reason = "no chunk left"
                    break
                self._work(claim)
        finally:
            signal.signal(signal.SIGTERM, previous)
        seconds = time.monotonic() - self.started
        return {"stopped": self.reason, "seconds": round(seconds), **self.counts}


def run(queue: Queue, name: str, until: float | None, detector=None) -> dict:
    """Work on the queue with `detector`, by default gheim's (`load`)."""
    wanted = detector_settings()
    made_for = {key: queue.settings.get(key) for key in wanted}
    if made_for != wanted:
        raise RuntimeError(f"the queue was made for {made_for}, this worker runs {wanted}")
    owner = f"{name}@{socket.gethostname()}"
    record = queue.root / "workers" / name / "worker.json"
    record.parent.mkdir(parents=True, exist_ok=True)
    source = hashlib.sha256()
    for module in (Path(__file__), Path(__file__).parents[1] / "text" / "queue.py"):
        source.update(module.read_bytes())
    facts = {
        "owner": owner,
        "until": until,
        "source_sha256": source.hexdigest(),
        "started": time.time(),
    }
    if detector is None:
        detector, environment = load()
        facts.update(environment)
    record.write_text(json.dumps(facts, indent=2) + "\n")
    result = Worker(queue, detector, owner, until).run()
    record.write_text(json.dumps({**facts, "finished": time.time(), **result}, indent=2) + "\n")
    return result
