"""The databases: the main one (`init-db`), the internal catalogue of files in it (`catalog`) and
the serving database the web server reads (`build`)."""

from __future__ import annotations

import typer

from ..config import settings
from .common import database_path

app = typer.Typer()


@app.command("init-db")
def init_db_cmd() -> None:
    """Create the SQLite database, tables, and the FTS5 index."""
    from ..db import init_db

    settings.ensure_dirs()
    init_db()
    typer.echo(f"database ready at {settings.database_url}")


@app.command()
def build() -> None:
    """Write the serving database the web server reads, from scratch, into DATA_DIR/serving.db."""
    from .. import build as stage

    for table, rows in stage.run(settings.serving_db, database_path(), settings.process_db).items():
        typer.echo(f"{table}: {rows} rows")


@app.command("catalog")
def catalog_command():
    """Refresh the website's document catalogue from the crawl records."""
    import fcntl

    from .. import catalog
    from ..communes import load_communes
    from ..db import init_db, session_scope

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    with (settings.data_dir / "catalog.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            typer.echo("catalogue refresh already running")
            return
        init_db()
        from ..db import engine

        if catalog.rebuild_if_outdated(engine):
            typer.echo("pdf_catalog had an older layout and is rebuilt")
        communes = load_communes()
        with session_scope() as session:
            catalog.upsert_communes(session, communes)
        with session_scope() as session:
            count = catalog.refresh(session, communes)
        typer.echo(f"{count} PDFs in the catalogue")
        pages = catalog.html_documents()
        if pages:
            typer.echo(f"{pages} HTML decision pages (not in the catalogue)")
