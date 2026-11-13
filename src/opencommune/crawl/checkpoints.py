"""Per-commune crawl checkpoints of one collector: a JSON file per commune in
`DATA_DIR/discovery/<family>/`, written atomically, and a queue lock so that two jobs never work the
same collector's queue at once."""

from __future__ import annotations

import datetime as dt
import fcntl
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from ..config import settings


class Checkpoints:
    def __init__(self, family: str, label: str):
        self.family, self.label = family, label

    def directory(self) -> Path:
        return settings.data_dir / "discovery" / self.family

    def read(self, bfs_id: int) -> dict | None:
        path = self.directory() / f"{bfs_id}.json"
        return json.loads(path.read_text()) if path.exists() else None

    def save(self, state: dict) -> None:
        """Write a commune's state, stamped with `updated_at`, through a temporary file."""
        self.directory().mkdir(parents=True, exist_ok=True)
        state["updated_at"] = dt.datetime.now(dt.UTC).isoformat()
        path = self.directory() / f"{state['bfs_id']}.json"
        part = path.with_suffix(".tmp")
        part.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
        part.replace(path)

    @contextmanager
    def locked(self) -> Iterator[None]:
        """The collector's queue for the duration of a job; ValueError when another job holds it."""
        self.directory().mkdir(parents=True, exist_ok=True)
        with (self.directory() / "queue.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError(f"another {self.label} job is already running") from None
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
