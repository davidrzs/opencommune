"""One OCR worker: it claims chunks of a queue, renders their pages and sends them to a vLLM server.

Pages are rendered with PyMuPDF to the queue's page size (2048 px on the longest edge for
LightOnOCR-3-4B, lightonocr/models.py) and sent as PNG with the text "grounding" (nothing in plain
mode), temperature 0.2, top_p 1.0, no output limit and thinking off, as LightOn's client does
(lightonocr/client.py). LightOn renders with pdfium; on 2026-11-12 MuPDF and pdfium gave the same
results within run-to-run noise.

Renderer processes keep pages ready, and `concurrency` requests stay in flight. The next chunk is
claimed as soon as the current one is handed to the renderers, so the server does not wait for the
last pages of a chunk. Each answer is appended to its chunk's result file at once.

Each PDF is checked against its name (SHA-256) before its pages are rendered; a missing or changed
file is a render error. A page that crashes or hangs its renderer is rendered again on its own, and
its error is recorded if it fails again. HTTP 4xx answers are final ("rejected"). Other request
errors are tried three times here, then left for a later holder of the chunk (queue.MAX_TRIES).

The worker stops when no chunk is left for it, at `until`, on SIGTERM, or when the server stops
answering. It releases its unfinished chunks on the way out.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import multiprocessing
import queue as queues
import signal
import socket
import threading
import time
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

import httpx
import pymupdf

from .queue import Claim, Queue

log = logging.getLogger(__name__)

MODEL = "lightonai/LightOnOCR-3-4B"
REVISION = "b71010f095dc3735de7ee6b9969bff8f8f50b39a"
MODE = "grounding"
LONGEST_EDGE = 2048  # LightOnOCR-3-4B and -0.8B (lightonocr/models.py)
SAMPLING = {"temperature": 0.2, "top_p": 1.0}
RENDER_TIMEOUT = 300  # seconds; a few vector plans never finish rendering
MAX_FAILURES_IN_A_ROW = 25  # the server is gone: stop rather than fail every page
RETRY_SECONDS = 5  # wait before the second try, twice that before the third
HEARTBEAT_SECONDS = 60
REPORT_SECONDS = 300
SERVER_FAILED = "the server stopped answering"
WORKER_FAILED = "the worker failed; see the log"
FAILURES = (SERVER_FAILED, WORKER_FAILED)


def reading_settings() -> dict:
    """How the pages of a queue are read; the queue records it and its workers follow it."""
    return {
        "model": MODEL,
        "revision": REVISION,
        "mode": MODE,
        "longest_edge": LONGEST_EDGE,
        "sampling": SAMPLING,
    }


def _quiet() -> None:
    pymupdf.TOOLS.mupdf_display_errors(False)


def render(path: str, sha: str, page: int, longest_edge: int) -> dict:
    """One page as PNG, `longest_edge` pixels on its longest edge."""
    started = time.perf_counter()
    try:
        with pymupdf.open(path) as doc:
            pdf_page = doc[page - 1]
            zoom = longest_edge / max(pdf_page.rect.width, pdf_page.rect.height)
            pixmap = pdf_page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
            png, width, height = pixmap.tobytes("png"), pixmap.width, pixmap.height
    except Exception as error:  # noqa: BLE001 - recorded per page
        return {"sha256": sha, "page": page, "error": f"{type(error).__name__}: {error}"}
    return {
        "sha256": sha,
        "page": page,
        "png": base64.b64encode(png).decode(),
        "width": width,
        "height": height,
        "render_s": round(time.perf_counter() - started, 3),
    }


def _pool(workers: int) -> ProcessPoolExecutor:
    # spawn, not fork: the process runs hundreds of threads when a pool is restarted
    context = multiprocessing.get_context("spawn")
    return ProcessPoolExecutor(workers, mp_context=context, initializer=_quiet)


def _kill(pool: ProcessPoolExecutor) -> None:
    for process in list((getattr(pool, "_processes", None) or {}).values()):
        process.kill()
    pool.shutdown(wait=False, cancel_futures=True)


def _render_alone(path: str, sha: str, page: int, longest_edge: int) -> dict:
    """One page in a fresh process, so a crash or hang is pinned on that page alone."""
    pool = _pool(1)
    try:
        return pool.submit(render, path, sha, page, longest_edge).result(timeout=RENDER_TIMEOUT)
    except BrokenProcessPool:
        return {"sha256": sha, "page": page, "error": "renderer crashed"}
    except TimeoutError:
        return {"sha256": sha, "page": page, "error": "render timeout"}
    finally:
        _kill(pool)


@dataclass
class _Held:
    """A chunk this worker holds, and how far it has got with it."""

    claim: Claim
    out: TextIO
    handed: int = 0  # pages given to the renderers or answered without them
    answered: int = 0  # of those, answered (or dropped, once the chunk was lost)
    all_handed: bool = False
    lost: bool = False
    closed: bool = False


class Worker:
    def __init__(
        self,
        queue: Queue,
        raw: Path,
        client: httpx.Client,
        owner: str,
        concurrency: int,
        render_workers: int,
        until: float | None,
    ):
        self.queue, self.raw, self.client, self.owner = queue, raw, client, owner
        self.model = queue.settings["model"]
        self.mode = queue.settings["mode"]
        self.longest_edge = queue.settings["longest_edge"]
        self.concurrency, self.render_workers, self.until = concurrency, render_workers, until
        self.pages: queues.Queue = queues.Queue(maxsize=concurrency)
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.held: list[_Held] = []
        self.counts: Counter = Counter()
        self.failures_in_a_row = 0
        self.checked: dict[str, str | None] = {}
        self.reason = "no chunk left"

    # --- chunks -----------------------------------------------------------------------------

    def _check(self, sha: str) -> str | None:
        """Why the PDF cannot be read, or None. Once per document and worker."""
        if sha not in self.checked:
            try:
                with (self.raw / f"{sha}.pdf").open("rb") as file:
                    digest = hashlib.file_digest(file, "sha256").hexdigest()
            except FileNotFoundError:
                self.checked[sha] = "no such file"
            else:
                self.checked[sha] = None if digest == sha else "the file's SHA-256 is not its name"
        return self.checked[sha]

    def _take(self, claim: Claim) -> tuple[_Held, list[tuple[str, int]]]:
        finished = self.queue.finished(claim.chunk)
        todo = [key for key in self.queue.pages(claim.chunk) if key not in finished]
        held = _Held(claim, (self.queue.root / "out" / f"{claim.chunk}.jsonl").open("a"))
        with self.lock:
            self.held.append(held)
        ready = []
        for sha, page in todo:
            problem = self._check(sha)
            if problem is None:
                ready.append((sha, page))
                continue
            with self.lock:
                held.handed += 1
            self._write(
                held, {"sha256": sha, "page": page, "status": "render_error", "error": problem}
            )
        log.info(
            "chunk %s: %d pages to read, %d answered before", claim.chunk, len(ready), len(finished)
        )
        return held, ready

    def _jobs(self):
        """(chunk, sha256, page) in order; the next chunk is claimed once one is handed out."""
        while not self.stop.is_set():
            claim = self.queue.claim(self.owner)
            if claim is None:
                return
            held, ready = self._take(claim)
            for sha, page in ready:
                if self.stop.is_set() or held.lost:
                    break
                with self.lock:
                    held.handed += 1
                yield held, sha, page
            with self.lock:
                held.all_handed = True
                self._close_if_complete(held)

    def _close_if_complete(self, held: _Held) -> None:
        """With the lock held: once every page handed out is answered, finish or release."""
        if held.closed or not held.all_handed or held.answered < held.handed:
            return
        held.closed = True
        held.out.close()
        self.held.remove(held)
        if held.lost:
            return
        if set(self.queue.pages(held.claim.chunk)) <= self.queue.finished(held.claim.chunk):
            self.queue.finish(held.claim)
            self.counts["chunks_finished"] += 1
        else:  # request errors to try again later
            self.queue.release(held.claim)
            self.counts["chunks_released"] += 1

    def _write(self, held: _Held, record: dict) -> None:
        with self.lock:
            if held.closed:  # released at a stop
                return
            if not held.lost:
                record = {**record, "worker": self.owner, "at": round(time.time(), 1)}
                held.out.write(json.dumps(record, ensure_ascii=False) + "\n")
                held.out.flush()
                self.counts[record["status"]] += 1
            held.answered += 1
            self._close_if_complete(held)

    def _beat(self) -> None:
        with self.lock:
            held = list(self.held)
        for item in held:
            if not item.lost and not self.queue.touch(item.claim):
                log.warning("chunk %s was taken over by another worker", item.claim.chunk)
                with self.lock:
                    item.lost = True
                    self._close_if_complete(item)

    def _release_all(self) -> None:
        with self.lock:
            for held in self.held:
                held.closed = True
                held.out.close()
                if not held.lost:
                    self.queue.release(held.claim)
                    self.counts["chunks_released"] += 1
            self.held.clear()

    def _halt(self, reason: str) -> None:
        with self.lock:
            if self.stop.is_set():
                return
            self.reason = reason
            self.stop.set()
        log.warning("stopping: %s", reason)

    # --- rendering and requests ---------------------------------------------------------------

    def _produce(self) -> None:
        """Render pages in worker processes into the page queue as they finish; a sentinel per
        consumer at the end. A page that crashes or hangs its renderer takes the pool down with
        it: the pool is then restarted and every page it held is rendered on its own, so only the
        culprit becomes an error."""
        pool = _pool(self.render_workers)
        pending: set = set()
        jobs = self._jobs()
        exhausted = False
        try:
            while (not exhausted or pending) and not self.stop.is_set():
                suspects = []
                while not exhausted and len(pending) < self.render_workers * 4:
                    try:
                        held, sha, page = next(jobs)
                    except StopIteration:
                        exhausted = True
                        break
                    path = str(self.raw / f"{sha}.pdf")
                    try:
                        future = pool.submit(render, path, sha, page, self.longest_edge)
                    except BrokenProcessPool:
                        suspects.append((held, sha, page))
                        break
                    future.job, future.submitted = (held, sha, page), time.monotonic()
                    pending.add(future)
                finished, pending = wait(pending, timeout=1, return_when=FIRST_COMPLETED)
                for future in finished:
                    try:
                        self.pages.put((future.job[0], future.result()))
                    except BrokenProcessPool:
                        suspects.append(future.job)
                overdue = any(time.monotonic() - f.submitted > RENDER_TIMEOUT for f in pending)
                if suspects or overdue:
                    suspects += [f.job for f in pending]
                    _kill(pool)
                    pool, pending = _pool(self.render_workers), set()
                    for held, sha, page in suspects:
                        result = _render_alone(
                            str(self.raw / f"{sha}.pdf"), sha, page, self.longest_edge
                        )
                        self.pages.put((held, result))
        except Exception:
            log.exception("renderer loop failed")
            self._halt(WORKER_FAILED)
        finally:
            _kill(pool)
            for _ in range(self.concurrency):
                self.pages.put(None)

    def _consume(self) -> None:
        while (item := self.pages.get()) is not None:
            held, page = item
            if self.stop.is_set():
                continue
            key = {"sha256": page["sha256"], "page": page["page"]}
            try:
                if "error" in page:
                    self._write(held, {**key, "status": "render_error", "error": page["error"]})
                else:
                    self._write(held, {**key, **self._ask(page)})
            except Exception:
                log.exception("writing the answer to %s failed", key)
                self._halt(WORKER_FAILED)

    def _answered(self, ok: bool) -> None:
        with self.lock:
            self.failures_in_a_row = 0 if ok else self.failures_in_a_row + 1
            failed = self.failures_in_a_row >= MAX_FAILURES_IN_A_ROW
        if failed:
            self._halt(SERVER_FAILED)

    def _ask(self, page: dict) -> dict:
        content = [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{page['png']}"}}
        ]
        if self.mode == "grounding":
            content.append({"type": "text", "text": "grounding"})
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": content}],
            **SAMPLING,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        sent = time.monotonic()
        message = ""
        for attempt in range(3):
            if attempt and self.stop.wait(RETRY_SECONDS * attempt):
                break
            try:
                response = self.client.post("/chat/completions", json=body)
            except httpx.HTTPError as error:
                message = f"{type(error).__name__}: {error}"
                continue
            if response.is_client_error:
                self._answered(True)
                return {
                    "status": "rejected",
                    "error": f"HTTP {response.status_code}: {response.text[:500]}",
                }
            if response.is_error:
                message = f"HTTP {response.status_code}: {response.text[:500]}"
                continue
            try:
                result = response.json()
                choice, usage = result["choices"][0], result["usage"]
                text = choice["message"].get("content") or ""
            except (ValueError, KeyError, IndexError, TypeError) as error:
                message = f"unexpected answer: {type(error).__name__}: {error}"
                continue
            self._answered(True)
            return {
                "status": "ok",
                "finish_reason": choice.get("finish_reason"),
                "prompt_tokens": usage["prompt_tokens"],
                "completion_tokens": usage["completion_tokens"],
                "width": page["width"],
                "height": page["height"],
                "render_s": page["render_s"],
                "request_s": round(time.monotonic() - sent, 3),
                "text": text,
            }
        self._answered(False)
        return {"status": "request_error", "error": message}

    # --- the run ------------------------------------------------------------------------------

    def run(self) -> dict:
        previous = signal.signal(signal.SIGTERM, lambda *_: self._halt("SIGTERM"))
        producer = threading.Thread(target=self._produce, daemon=True)
        consumers = [
            threading.Thread(target=self._consume, daemon=True) for _ in range(self.concurrency)
        ]
        producer.start()
        for thread in consumers:
            thread.start()
        started = last_beat = last_report = time.monotonic()
        try:
            while not self.stop.is_set() and any(thread.is_alive() for thread in consumers):
                time.sleep(1)
                if self.until is not None and time.time() >= self.until:
                    self._halt("time is up")
                now = time.monotonic()
                if now - last_beat >= HEARTBEAT_SECONDS:
                    last_beat = now
                    self._beat()
                if now - last_report >= REPORT_SECONDS:
                    last_report = now
                    log.info(
                        "%.0f s: %s, %.2f pages/s",
                        now - started,
                        dict(self.counts),
                        self.counts["ok"] / (now - started),
                    )
        finally:
            signal.signal(signal.SIGTERM, previous)
            self._release_all()
        return {"stopped": self.reason, "seconds": round(time.monotonic() - started), **self.counts}


def run(
    queue: Queue,
    raw: Path,
    url: str,
    name: str,
    concurrency: int,
    render_workers: int,
    until: float | None,
) -> dict:
    """Work on the queue with the vLLM server at `url` (its OpenAI API, ending in /v1)."""
    owner = f"{name}@{socket.gethostname()}"
    record = queue.root / "workers" / name / "worker.json"
    record.parent.mkdir(parents=True, exist_ok=True)
    source = hashlib.sha256()
    for module in ("ocr.py", "queue.py"):
        source.update((Path(__file__).parent / module).read_bytes())
    facts = {
        "owner": owner,
        "url": url,
        "raw": str(raw),
        "concurrency": concurrency,
        "render_workers": render_workers,
        "until": until,
        "pymupdf": pymupdf.__version__,
        "httpx": httpx.__version__,
        "source_sha256": source.hexdigest(),
        "started": time.time(),
    }
    record.write_text(json.dumps(facts, indent=2) + "\n")
    with httpx.Client(
        base_url=url,
        timeout=httpx.Timeout(None, connect=30),  # no output limit: a page may run long
        limits=httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency),
        trust_env=False,
    ) as client:
        response = client.get("/models", timeout=60)
        response.raise_for_status()
        served = [model["id"] for model in response.json()["data"]]
        if queue.settings["model"] not in served:
            raise RuntimeError(
                f"the server serves {served}, the queue wants {queue.settings['model']}"
            )
        worker = Worker(queue, raw, client, owner, concurrency, render_workers, until)
        result = worker.run()
    record.write_text(json.dumps({**facts, "finished": time.time(), **result}, indent=2) + "\n")
    return result
