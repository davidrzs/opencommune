"""The processing database: answers, failures and the state of classification jobs.

One SQLite file in DATA_DIR. It holds paid results, so it is never rebuilt and never published:
answers may name people. Each answer is keyed by the PDF's sha256 and the prompt version, so the
answers of several prompt versions sit side by side and a document is never sent twice for one.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

# Requests that expired or were cancelled never ran, so they say nothing against the document.
HELD_AGAINST = "reason NOT IN ('batch_expired', 'batch_cancelled')"

SCHEMA = """
CREATE TABLE IF NOT EXISTS renderers (
    version TEXT PRIMARY KEY,
    renderer TEXT NOT NULL,         -- library and version that rendered the version's requests
    first_used TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS answers (
    sha256 TEXT NOT NULL,
    version TEXT NOT NULL,
    job TEXT NOT NULL,
    answer TEXT NOT NULL,           -- JSON, as the model returned it
    model TEXT,                     -- as OpenAI reported it
    pages INTEGER,
    pages_sent INTEGER,
    jpeg_quality INTEGER,
    input_tokens INTEGER,
    output_tokens INTEGER,
    reasoning_tokens INTEGER,
    answered_at TEXT NOT NULL,
    PRIMARY KEY (sha256, version)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS failures (
    sha256 TEXT NOT NULL,
    version TEXT NOT NULL,
    job TEXT NOT NULL,
    stage TEXT NOT NULL CHECK (stage IN ('render', 'request')),
    reason TEXT NOT NULL,           -- an error code, or a short text
    detail TEXT,                    -- JSON: the error as returned
    input_tokens INTEGER,
    output_tokens INTEGER,
    failed_at TEXT NOT NULL,
    UNIQUE (sha256, version, job, stage, failed_at)
);
CREATE INDEX IF NOT EXISTS failures_by_document ON failures (version, sha256);
CREATE TABLE IF NOT EXISTS jobs (
    name TEXT PRIMARY KEY,
    version TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS requests (
    job TEXT NOT NULL REFERENCES jobs (name),
    sha256 TEXT NOT NULL,
    file INTEGER NOT NULL,          -- the input file on scratch that holds the request
    pages INTEGER NOT NULL,
    pages_sent INTEGER NOT NULL,
    jpeg_quality INTEGER NOT NULL,
    estimated_tokens INTEGER NOT NULL,
    PRIMARY KEY (job, sha256)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS batches (
    job TEXT NOT NULL REFERENCES jobs (name),
    file INTEGER NOT NULL,
    batch_id TEXT NOT NULL UNIQUE,
    sent_at TEXT NOT NULL,
    fetched_at TEXT,                -- results stored
    cleaned_at TEXT,                -- files deleted at OpenAI
    PRIMARY KEY (job, file)
);
"""


def now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Batch:
    file: int
    batch_id: str
    fetched: bool
    cleaned: bool


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        new = not path.exists()
        self.db = sqlite3.connect(path, timeout=60, isolation_level=None)
        if new:
            path.chmod(0o600)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """The block is stored as a whole, or not at all."""
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        self.db.execute("COMMIT")

    # --- documents ------------------------------------------------------------------------------

    def answered(self, version: str) -> set[str]:
        query = "SELECT sha256 FROM answers WHERE version = ?"
        return {sha for (sha,) in self.db.execute(query, (version,))}

    def failure_counts(self, version: str) -> Counter[str]:
        """Failures held against each document that has no answer."""
        query = f"""
            SELECT sha256, count(*) FROM failures
            WHERE version = ? AND {HELD_AGAINST}
              AND sha256 NOT IN (SELECT sha256 FROM answers WHERE version = ?)
            GROUP BY sha256"""
        return Counter(dict(self.db.execute(query, (version, version))))

    def answers(self, version: str) -> Iterator[tuple[str, dict]]:
        query = "SELECT sha256, answer FROM answers WHERE version = ? ORDER BY sha256"
        for sha, answer in self.db.execute(query, (version,)):
            yield sha, json.loads(answer)

    def add_answer(
        self,
        sha256: str,
        version: str,
        job: str,
        answer: dict,
        usage: dict,
        model: str | None = None,
        pages: int | None = None,
        pages_sent: int | None = None,
        jpeg_quality: int | None = None,
        at: str | None = None,
    ) -> bool:
        """False if the document already had an answer for the version; the first one stays."""
        cursor = self.db.execute(
            """INSERT OR IGNORE INTO answers VALUES
               (:sha256, :version, :job, :answer, :model, :pages, :pages_sent, :jpeg_quality,
                :input_tokens, :output_tokens, :reasoning_tokens, :answered_at)""",
            {
                "sha256": sha256,
                "version": version,
                "job": job,
                "answer": json.dumps(answer, ensure_ascii=False),
                "model": model,
                "pages": pages,
                "pages_sent": pages_sent,
                "jpeg_quality": jpeg_quality,
                "answered_at": at or now(),
                **_tokens(usage),
            },
        )
        return cursor.rowcount == 1

    def add_failure(
        self,
        sha256: str,
        version: str,
        job: str,
        stage: str,
        reason: str,
        detail=None,
        usage: dict | None = None,
        at: str | None = None,
    ) -> bool:
        tokens = _tokens(usage or {})
        cursor = self.db.execute(
            "INSERT OR IGNORE INTO failures VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                sha256,
                version,
                job,
                stage,
                reason,
                None if detail is None else json.dumps(detail, ensure_ascii=False),
                tokens["input_tokens"],
                tokens["output_tokens"],
                at or now(),
            ),
        )
        return cursor.rowcount == 1

    def freeze_renderer(self, version: str, renderer: str) -> None:
        """A version's requests are always rendered by the same library version: another one draws
        other images, and the answers would not be comparable."""
        self.db.execute(
            "INSERT OR IGNORE INTO renderers VALUES (?, ?, ?)", (version, renderer, now())
        )
        (frozen,) = self.db.execute(
            "SELECT renderer FROM renderers WHERE version = ?", (version,)
        ).fetchone()
        if frozen != renderer:
            raise ValueError(f"{version} was rendered with {frozen}; installed is {renderer}")

    # --- jobs -----------------------------------------------------------------------------------

    def add_job(self, name: str, version: str) -> None:
        self.db.execute("INSERT OR IGNORE INTO jobs VALUES (?, ?, ?)", (name, version, now()))
        (frozen,) = self.db.execute("SELECT version FROM jobs WHERE name = ?", (name,)).fetchone()
        if frozen != version:
            raise ValueError(f"job {name} belongs to {frozen}")

    def job_version(self, name: str) -> str:
        row = self.db.execute("SELECT version FROM jobs WHERE name = ?", (name,)).fetchone()
        if row is None:
            raise ValueError(f"no job {name}")
        return row[0]

    def open_jobs(self, version: str) -> list[str]:
        """Jobs with a request whose results are not stored yet."""
        query = """
            SELECT DISTINCT r.job FROM requests r JOIN jobs j ON j.name = r.job
            LEFT JOIN batches b ON b.job = r.job AND b.file = r.file
            WHERE j.version = ? AND b.fetched_at IS NULL ORDER BY r.job"""
        return [job for (job,) in self.db.execute(query, (version,))]

    def add_request(self, job: str, sha256: str, file: int, rendered) -> None:
        self.db.execute(
            "INSERT INTO requests VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                job,
                sha256,
                file,
                rendered.pages,
                rendered.pages_sent,
                rendered.jpeg_quality,
                rendered.estimated_tokens,
            ),
        )

    def requested(self, job: str) -> set[str]:
        return {
            sha for (sha,) in self.db.execute("SELECT sha256 FROM requests WHERE job = ?", (job,))
        }

    def request(self, job: str, sha256: str) -> dict:
        row = self.db.execute(
            "SELECT pages, pages_sent, jpeg_quality FROM requests WHERE job = ? AND sha256 = ?",
            (job, sha256),
        ).fetchone()
        return dict(zip(("pages", "pages_sent", "jpeg_quality"), row, strict=True)) if row else {}

    def file_sizes(self, job: str) -> dict[int, tuple[int, int, int]]:
        """Per input file: requests, pages sent, estimated image tokens."""
        query = """SELECT file, count(*), sum(pages_sent), sum(estimated_tokens) FROM requests
                   WHERE job = ? GROUP BY file"""
        return {file: rest for file, *rest in self.db.execute(query, (job,))}

    def add_batch(self, job: str, file: int, batch_id: str) -> None:
        self.db.execute(
            "INSERT INTO batches (job, file, batch_id, sent_at) VALUES (?, ?, ?, ?)",
            (job, file, batch_id, now()),
        )

    def batches(self, job: str) -> dict[int, Batch]:
        query = """SELECT file, batch_id, fetched_at IS NOT NULL, cleaned_at IS NOT NULL
                   FROM batches WHERE job = ?"""
        return {row[0]: Batch(*row) for row in self.db.execute(query, (job,))}

    def mark(self, batch_id: str, column: str) -> None:
        if column not in ("fetched_at", "cleaned_at"):
            raise ValueError(column)
        self.db.execute(f"UPDATE batches SET {column} = ? WHERE batch_id = ?", (now(), batch_id))

    # --- reports --------------------------------------------------------------------------------

    def usage(self, version: str, job: str | None = None) -> tuple[int, int]:
        """Input and output tokens billed, answers and failures together."""
        where = "version = ?" + (" AND job = ?" if job else "")
        params = (version, job) if job else (version,)
        total = [0, 0]
        for table in ("answers", "failures"):
            row = self.db.execute(
                f"SELECT total(input_tokens), total(output_tokens) FROM {table} WHERE {where}",
                params,
            ).fetchone()
            total = [total[0] + int(row[0]), total[1] + int(row[1])]
        return total[0], total[1]

    def outcome_counts(self, version: str, job: str) -> tuple[int, int]:
        """Usable answers and outcomes of the job's requests, leaving out requests that never ran."""
        (good,) = self.db.execute(
            "SELECT count(*) FROM answers WHERE version = ? AND job = ?", (version, job)
        ).fetchone()
        (bad,) = self.db.execute(
            f"""SELECT count(*) FROM failures WHERE version = ? AND job = ? AND stage = 'request'
                AND {HELD_AGAINST}""",
            (version, job),
        ).fetchone()
        return good, good + bad


def _tokens(usage: dict) -> dict:
    """Token counts from a Responses API usage object."""
    details = usage.get("output_tokens_details") or {}
    return {
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "reasoning_tokens": details.get("reasoning_tokens"),
    }
