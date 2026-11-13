"""Engine, sessions, and schema creation including the FTS5 index and its sync triggers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import settings
from .models import Base

FTS_SQL = [
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS decisions_fts USING fts5(
        title, summary,
        content='decisions', content_rowid='rid',
        tokenize='unicode61 remove_diacritics 2'
    )
    """,
    """
    CREATE TRIGGER IF NOT EXISTS decisions_ai AFTER INSERT ON decisions BEGIN
        INSERT INTO decisions_fts(rowid, title, summary) VALUES (new.rid, new.title, new.summary);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS decisions_ad AFTER DELETE ON decisions BEGIN
        INSERT INTO decisions_fts(decisions_fts, rowid, title, summary)
        VALUES ('delete', old.rid, old.title, old.summary);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS decisions_au AFTER UPDATE ON decisions BEGIN
        INSERT INTO decisions_fts(decisions_fts, rowid, title, summary)
        VALUES ('delete', old.rid, old.title, old.summary);
        INSERT INTO decisions_fts(rowid, title, summary) VALUES (new.rid, new.title, new.summary);
    END
    """,
]


def _make_engine(url: str) -> Engine:
    engine = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


engine = _make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db(target: Engine | None = None) -> None:
    eng = target or engine
    if eng.url.database and eng.url.database != ":memory:":
        Path(eng.url.database).parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(eng)
    with eng.begin() as conn:
        for stmt in FTS_SQL:
            conn.execute(text(stmt))


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
