"""`opencommune privacy`: the privacy check of page text with gheim.

Queues are named and live in DATA_DIR/privacy/queues/<name>; `import` copies one into
DATA_DIR/privacy.db.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import typer

from ..config import settings
from .common import file_sha256, named, now, reported_errors

app = typer.Typer(
    no_args_is_help=True, help="The privacy check: personal data in page text, found by gheim."
)


def _queue(name: str) -> Path:
    root = named(settings.privacy_dir / "queues", name)
    if not root.is_dir():
        raise typer.BadParameter(f"no queue {name}")
    return root


@app.command("queue")
def queue(
    name: str = typer.Argument(..., help="A new name; a queue is never changed"),
    chunk_pages: int = typer.Option(2000, min=1, help="Pages per chunk, the unit a worker claims"),
) -> None:
    """Write the pages to check, with their text, as a queue of chunks for `privacy detect`.

    The pages are those in scope (opencommune.scope) with usable text in DATA_DIR/text.db."""
    from ..privacy import detect
    from ..text.queue import Queue

    target = named(settings.privacy_dir / "queues", name)
    if target.exists():
        raise typer.BadParameter(f"queue {name} exists; a queue is never changed")
    if not settings.text_db.exists():
        raise typer.BadParameter("no text.db; import a text layer pass first")
    chosen = {
        "created": now(),
        "rule": detect.RULE,
        "serving_db_sha256": file_sha256(settings.serving_db),
        "text_db_sha256": file_sha256(settings.text_db),
        **detect.detector_settings(),
    }
    items = detect.choose(settings.serving_db, settings.text_db)
    created = Queue.create(target, items, chunk_pages, chosen)
    pages = created.settings["pages"]
    typer.echo(json.dumps({"queue": str(target), "pages": pages, "chunks": len(created.chunks())}))


@app.command("detect")
def detect_(
    name: str = typer.Argument(..., help="The queue"),
    worker: str | None = typer.Option(None, help="This worker's name, e.g. the Slurm job id"),
    until: float | None = typer.Option(None, help="Unix time at which to stop"),
) -> None:
    """Check the pages of a queue until no chunk is left for this worker, `until`, or SIGTERM.

    Needs gheim (`uv sync --extra privacy`). Exits with 2 when the detector failed page after
    page."""
    import socket

    from ..privacy import detect
    from ..text.queue import Queue

    root = _queue(name)
    label = worker or f"{socket.gethostname()}-{os.getpid()}"
    with reported_errors():
        result = detect.run(Queue(root), label, until)
    typer.echo(json.dumps(result))
    if result["stopped"] == detect.FAILED:
        raise typer.Exit(code=2)


@app.command("import")
def import_(name: str = typer.Argument(..., help="The queue, finished or not")) -> None:
    """Copy what a queue found into DATA_DIR/privacy.db. Importing a queue again replaces its rows."""
    from ..privacy import store
    from ..text.queue import Queue

    root = _queue(name)
    db = store.connect(settings.privacy_db)
    try:
        result = store.import_queue(db, name, Queue(root))
    finally:
        db.close()
    typer.echo(json.dumps(result))


@app.command("status")
def status(name: str = typer.Argument(..., help="The queue")) -> None:
    """Chunks by state and pages by answer."""
    from ..text.queue import Queue

    typer.echo(json.dumps(Queue(_queue(name)).status()))
