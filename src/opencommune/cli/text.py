"""`opencommune text`: the text of each page, from the PDF's text layer or by OCR.

Passes and queues are named and live in DATA_DIR/text: `layers/<name>/` holds a text layer pass,
`queues/<name>/` an OCR queue with its answers. `import` copies either into DATA_DIR/text.db.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import typer

from ..config import settings
from .common import reported_errors

app = typer.Typer(
    no_args_is_help=True,
    help="The text of each page: the PDF's text layer, and OCR for the pages without one.",
)

NAME = re.compile(r"[a-z0-9][a-z0-9._-]*")


def _named(kind: str, name: str) -> Path:
    if not NAME.fullmatch(name):
        raise typer.BadParameter(f"{name!r}: lower-case letters, digits, '.', '_' and '-' only")
    return settings.text_dir / kind / name


def _types(text: str) -> list[str]:
    return [part.strip() for part in text.split(",") if part.strip()]


def _sha256(path: Path) -> str:
    import hashlib

    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def _now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat(timespec="seconds")


@app.command("layer")
def layer(
    name: str = typer.Argument(..., help="The pass; a rerun with the same name goes on"),
    sections: str = typer.Option(..., help="Comma-separated section types, e.g. budget,accounts"),
    margin: int = typer.Option(..., min=0, help="Pages on either side of a section to include"),
    workers: int = typer.Option(8, min=1, help="Documents read at once"),
) -> None:
    """Read the text layer of every page of the given section types with PyMuPDF.

    Writes pages.jsonl (one line per page, see opencommune.text.layer) and settings.json."""
    import pymupdf

    from ..text import layer as text_layer

    out = _named("layers", name)
    types = _types(sections)
    if not types:
        raise typer.BadParameter("name at least one section type")
    chosen = {"sections": types, "margin": margin}
    record = out / "settings.json"
    if record.exists():
        before = json.loads(record.read_text())
        if {key: before[key] for key in chosen} != chosen:
            raise typer.BadParameter(
                f"{name} holds pages of {before['sections']}, margin {before['margin']}"
            )
    else:
        out.mkdir(parents=True)
        facts = {
            **chosen,
            "serving_db": str(settings.serving_db),
            "serving_db_sha256": _sha256(settings.serving_db),
            "raw": str(settings.raw_dir),
            "pymupdf": pymupdf.__version__,
            "started": _now(),
        }
        record.write_text(json.dumps(facts, indent=2) + "\n")
    pages = text_layer.section_pages(settings.serving_db, types, margin)
    counts = text_layer.measure(
        pages, settings.raw_dir, out / "pages.jsonl", min(workers, os.cpu_count() or 1)
    )
    typer.echo(json.dumps(counts))


@app.command("queue")
def queue(
    name: str = typer.Argument(..., help="A new name; a queue is never changed"),
    layer: str = typer.Option(..., help="The text layer pass to choose pages from"),
    chars_below: int = typer.Option(
        ...,
        min=1,
        help="OCR the pages with fewer non-space characters than this in their text layer",
    ),
    first: str = typer.Option("", help="Comma-separated section types whose pages are read first"),
    chunk_pages: int = typer.Option(500, min=1, help="Pages per chunk, the unit a worker claims"),
) -> None:
    """Choose the pages for OCR and write them as a queue of chunks for `text ocr`."""
    from ..text import ocr as text_ocr
    from ..text.queue import Queue, select

    target, source = _named("queues", name), _named("layers", layer)
    if target.exists():
        raise typer.BadParameter(f"queue {name} exists; a queue is never changed")
    if not (source / "pages.jsonl").exists():
        raise typer.BadParameter(f"no text layer pass {layer}")
    first_types = _types(first)
    with (source / "pages.jsonl").open() as lines:
        pages, counts = select(lines, chars_below, first_types)
    chosen = {
        "created": _now(),
        "rule": f"pages whose text layer has fewer than {chars_below} non-space characters",
        "chars_below": chars_below,
        "first": first_types,
        "layer": layer,
        "layer_settings": json.loads((source / "settings.json").read_text()),
        "layer_sha256": _sha256(source / "pages.jsonl"),
        **counts,
        **text_ocr.reading_settings(),
    }
    created = Queue.create(target, pages, chunk_pages, chosen)
    typer.echo(json.dumps({"queue": str(target), **counts, "chunks": len(created.chunks())}))


@app.command("ocr")
def ocr(
    name: str = typer.Argument(..., help="The queue"),
    url: str = typer.Option(
        ..., help="The vLLM server's OpenAI API, e.g. http://127.0.0.1:8100/v1"
    ),
    worker: str | None = typer.Option(None, help="This worker's name, e.g. the Slurm job id"),
    concurrency: int = typer.Option(256, min=1, help="Pages in flight; changes speed, not output"),
    render_workers: int = typer.Option(6, min=1, help="Renderer processes"),
    until: float | None = typer.Option(None, help="Unix time at which to stop"),
) -> None:
    """Work on a queue until no chunk is left for this worker, `until`, or SIGTERM.

    Reads the PDFs from DATA_DIR's raw directory. Exits with 2 when the server stopped answering
    or the worker failed."""
    import logging
    import socket
    import sys

    from ..text import ocr as text_ocr
    from ..text.queue import Queue

    root = _named("queues", name)
    if not root.is_dir():
        raise typer.BadParameter(f"no queue {name}")
    label = worker or f"{socket.gethostname()}-{os.getpid()}"
    with reported_errors():
        result = text_ocr.run(
            Queue(root), settings.raw_dir, url, label, concurrency, render_workers, until
        )
    typer.echo(json.dumps(result))
    sys.stdout.flush()
    logging.shutdown()
    # Requests still in flight and renderers stuck on a page would keep the process alive.
    os._exit(2 if result["stopped"] in text_ocr.FAILURES else 0)


@app.command("import")
def import_(
    layer: str | None = typer.Option(None, help="A text layer pass"),
    queue: str | None = typer.Option(None, help="An OCR queue, finished or not"),
) -> None:
    """Copy a text layer pass or an OCR queue into DATA_DIR/text.db.

    Importing a run again replaces its rows."""
    from ..text import store
    from ..text.queue import Queue

    if (layer is None) == (queue is None):
        raise typer.BadParameter("name either --layer or --queue")
    if layer is not None:
        root = _named("layers", layer)
        if not (root / "pages.jsonl").exists():
            raise typer.BadParameter(f"no text layer pass {layer}")
    else:
        root = _named("queues", queue)
        if not root.is_dir():
            raise typer.BadParameter(f"no queue {queue}")
    db = store.connect(settings.text_db)
    try:
        if layer is not None:
            result = store.import_layer(db, layer, root)
        else:
            result = store.import_queue(db, queue, Queue(root))
    finally:
        db.close()
    typer.echo(json.dumps(result))


@app.command("status")
def status(name: str = typer.Argument(..., help="The queue")) -> None:
    """Chunks by state and pages by answer."""
    from ..text.queue import Queue

    root = _named("queues", name)
    if not root.is_dir():
        raise typer.BadParameter(f"no queue {name}")
    typer.echo(json.dumps(Queue(root).status()))
