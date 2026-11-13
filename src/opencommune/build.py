"""Build stage: the serving tables the Rust server reads (`serving.sql`), rebuilt from scratch.

The server reads SQLite only. This stage copies the coverage register (`data/register/`) and the
current access failures (`discovery/access/`, one row per commune and website) into the main
database, next to the catalogue and the decision tables, and leaves the file out of WAL mode so a
read-only server needs no `-shm` file beside it.
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import closing
from importlib.resources import files
from pathlib import Path

from .crawl import access
from .register import RegisterEntry, load_register, publication_note

log = logging.getLogger(__name__)

TABLES = ("register", "register_publications", "access_observations")


def register_note(entry: RegisterEntry, body: str | None) -> str | None:
    """The note the commune list shows: for the commune's first body, else for the first
    publication with an obstacle or a `how`."""
    pub = entry.publication_for(body) if body else None
    if pub is None:
        pub = next((p for p in entry.publications if p.obstacle or p.how), None)
    return publication_note(entry, pub)


def run(db_path: Path) -> dict[str, int]:
    """Drop and refill the serving tables in one transaction; return the row count per table."""
    register = load_register()
    with closing(sqlite3.connect(db_path)) as db:
        with db:
            for table in TABLES:
                db.execute(f"DROP TABLE IF EXISTS {table}")
            db.executescript(files(__package__).joinpath("serving.sql").read_text())
            first_body = dict(
                db.execute("SELECT commune_bfs_id, min(body) FROM holdings GROUP BY commune_bfs_id")
            )
            for e in register:
                db.execute(
                    "INSERT INTO register VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        e.bfs_id,
                        e.name,
                        e.canton,
                        e.status,
                        e.website,
                        e.vendor,
                        None if e.reachable is None else int(e.reachable),
                        e.checked.isoformat() if e.checked else None,
                        e.checked_by,
                        e.notes,
                        register_note(e, first_body.get(e.bfs_id)),
                    ),
                )
                for i, p in enumerate(e.publications):
                    d = p.model_dump(by_alias=True)
                    db.execute(
                        "INSERT INTO register_publications VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            e.bfs_id,
                            i,
                            d["body"],
                            d["kind"],
                            d["status"],
                            d["listing_url"],
                            d["from"],
                            d["to"],
                            d["cadence"],
                            d["obstacle"],
                            d["how"],
                        ),
                    )
            for bfs_id, sites in access.by_commune(register).items():
                db.executemany(
                    "INSERT INTO access_observations VALUES (?,?,?,?,?,?)",
                    [
                        (
                            bfs_id,
                            site["source_url"],
                            site["status"],
                            site["checked_at"],
                            site["robots_url"],
                            site["restricted_at"],
                        )
                        for site in sites
                    ],
                )
        counts = {t: db.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in TABLES}
        db.execute("PRAGMA journal_mode=DELETE")
    for table, n in counts.items():
        log.info("build: %s %d rows", table, n)
    return counts
