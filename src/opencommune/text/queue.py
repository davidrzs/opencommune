"""A queue of pages on a shared file system, worked by any number of workers at once: OCR
(`text.ocr`) and the privacy check (`privacy.detect`) use it.

    QUEUE/settings.json        how the pages were chosen and how they are to be read
    QUEUE/chunks/NNNNN.jsonl   the pages of each chunk in order, {"sha256", "page"} per line and
                               whatever else the worker needs (the privacy check: the text)
    QUEUE/claims/NNNNN.K       attempt K at a chunk; its holder touches the file every minute
    QUEUE/out/NNNNN.jsonl      one JSON line per answer, appended by the chunk's holder
    QUEUE/done/NNNNN           written once every page of the chunk has a final answer
    QUEUE/workers/NAME/        what each worker ran with, and its job's logs

A worker claims a chunk by creating its next attempt file, which only one worker can do (O_EXCL). A
chunk is free when it is not done and its newest attempt is gone (released) or has not been touched
for STALE_SECONDS (its holder died). The holder of an older attempt has lost the chunk and stops
writing to it. Pages that already have a final answer in the chunk's result file are skipped, so a
chunk goes on where its last holder stopped.

A final answer is "ok", "render_error" or "rejected" (the server refused the request), or the
MAX_TRIES-th error of a page ("request_error" for OCR, "error" for the privacy check). Earlier
errors leave the page for a later holder.
"""

from __future__ import annotations

import json
import os
import time
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

STALE_SECONDS = 15 * 60
MAX_TRIES = 3
FINAL = ("ok", "render_error", "rejected")
DIRECTORIES = ("chunks", "claims", "out", "done", "workers")


@dataclass(frozen=True)
class Claim:
    chunk: str
    path: Path


class Queue:
    def __init__(self, root: Path):
        self.root = root
        self.settings = json.loads((root / "settings.json").read_text())
        self._chunks = sorted(path.stem for path in (root / "chunks").glob("*.jsonl"))

    @classmethod
    def create(cls, root: Path, items: Iterable[dict], chunk_pages: int, settings: dict) -> Queue:
        """Write a new queue of `items`, each {"sha256", "page", ...}, in their order. An existing
        directory is never changed."""
        root.mkdir(parents=True)
        for name in DIRECTORIES:
            (root / name).mkdir()
        chunks = pages = 0
        lines: list[str] = []
        for item in items:
            lines.append(json.dumps(item, ensure_ascii=False) + "\n")
            pages += 1
            if len(lines) == chunk_pages:
                (root / "chunks" / f"{chunks:05d}.jsonl").write_text("".join(lines))
                chunks, lines = chunks + 1, []
        if lines:
            (root / "chunks" / f"{chunks:05d}.jsonl").write_text("".join(lines))
            chunks += 1
        settings = {**settings, "pages": pages, "chunk_pages": chunk_pages, "chunks": chunks}
        (root / "settings.json").write_text(
            json.dumps(settings, indent=2, ensure_ascii=False) + "\n"
        )
        return cls(root)

    def chunks(self) -> list[str]:
        return self._chunks

    def items(self, chunk: str) -> list[dict]:
        with (self.root / "chunks" / f"{chunk}.jsonl").open() as lines:
            return [json.loads(line) for line in lines]

    def pages(self, chunk: str) -> list[tuple[str, int]]:
        return [(item["sha256"], item["page"]) for item in self.items(chunk)]

    def answers(self, chunk: str) -> list[dict]:
        path = self.root / "out" / f"{chunk}.jsonl"
        if not path.exists():
            return []
        records = []
        with path.open() as lines:
            for line in lines:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:  # cut off when a worker was stopped
                    continue
        return records

    def counting(self, chunk: str) -> dict[tuple[str, int], tuple[dict, int]]:
        """Per page of the chunk with an answer: the answer that counts (the first final one, else
        the last error) and the page's number of errors."""
        found: dict[tuple[str, int], tuple[dict, int]] = {}
        for record in self.answers(chunk):
            key = (record["sha256"], record["page"])
            before, tries = found.get(key, (None, 0))
            if before is not None and before["status"] in FINAL:
                continue  # answered twice after a claim was taken over
            found[key] = (record, tries + (record["status"] not in FINAL))
        return found

    def finished(self, chunk: str) -> set[tuple[str, int]]:
        """Pages of the chunk with a final answer."""
        return {
            key
            for key, (record, tries) in self.counting(chunk).items()
            if record["status"] in FINAL or tries >= MAX_TRIES
        }

    def is_done(self, chunk: str) -> bool:
        return (self.root / "done" / chunk).exists()

    def _attempts(self, chunk: str) -> list[tuple[int, Path]]:
        found = []
        for path in (self.root / "claims").glob(f"{chunk}.*"):
            suffix = path.name.rsplit(".", 1)[1]
            if suffix.isdigit():
                found.append((int(suffix), path))
        return sorted(found)

    def _age(self, path: Path) -> float | None:
        try:
            return time.time() - path.stat().st_mtime
        except FileNotFoundError:
            return None

    def claim(self, owner: str) -> Claim | None:
        """Claim the first free chunk, or None when every chunk is done or held."""
        for chunk in self._chunks:
            if self.is_done(chunk):
                continue
            attempts = self._attempts(chunk)
            attempt = 1
            if attempts:
                newest, path = attempts[-1]
                age = self._age(path)
                if age is not None and age < STALE_SECONDS:
                    continue
                attempt = newest + 1 if age is not None else newest
            path = self.root / "claims" / f"{chunk}.{attempt}"
            try:
                handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:  # another worker was quicker
                continue
            with os.fdopen(handle, "w") as file:
                file.write(json.dumps({"owner": owner, "claimed": time.time()}) + "\n")
            claim = Claim(chunk, path)
            if self.is_done(chunk):  # finished while we looked
                self.release(claim)
                continue
            return claim
        return None

    def holds(self, claim: Claim) -> bool:
        attempts = self._attempts(claim.chunk)
        return bool(attempts) and attempts[-1][1] == claim.path

    def touch(self, claim: Claim) -> bool:
        """Renew the claim; False when it was lost to another worker."""
        if not self.holds(claim):
            return False
        try:
            os.utime(claim.path)
        except FileNotFoundError:
            return False
        return True

    def release(self, claim: Claim) -> None:
        claim.path.unlink(missing_ok=True)

    def finish(self, claim: Claim) -> None:
        (self.root / "done" / claim.chunk).touch()
        self.release(claim)

    def status(self) -> dict:
        """Chunks by state and pages by answer, from the files as they are now."""
        chunks: Counter = Counter()
        pages: Counter = Counter()
        tokens = 0
        recent = 0
        hour_ago = time.time() - 3600
        for chunk in self._chunks:
            if self.is_done(chunk):
                chunks["done"] += 1
            else:
                attempts = self._attempts(chunk)
                age = self._age(attempts[-1][1]) if attempts else None
                if age is None:
                    chunks["open"] += 1
                else:
                    chunks["held" if age < STALE_SECONDS else "stale"] += 1
            for record, tries in self.counting(chunk).values():
                status = record["status"]
                if status == "ok":
                    tokens += record.get("completion_tokens", 0)
                    recent += record.get("at", 0) > hour_ago
                    if record.get("finish_reason") == "length":
                        status = "ok_length"
                elif status not in FINAL and tries < MAX_TRIES:
                    status += "_retry"
                pages[status] += 1
        answered = sum(n for status, n in pages.items() if not status.endswith("_retry"))
        return {
            "chunks": {"total": len(self._chunks), **chunks},
            "pages": {"total": self.settings["pages"], "answered": answered, **pages},
            "completion_tokens": tokens,
            "ok_last_hour": recent,
        }
