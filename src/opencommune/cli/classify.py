"""`opencommune classify`: document classification with a language model."""

from __future__ import annotations

import os
from pathlib import Path

import typer

from ..config import settings
from .common import database_path, reported_errors

app = typer.Typer(
    no_args_is_help=True,
    help="Classify documents with a language model, through OpenAI's Batch API.",
)


def _classify_paths():
    from ..classify.jobs import Paths

    return Paths(settings.process_db, settings.batch_outputs_dir, settings.scratch)


@app.command("prompts")
def classify_prompts() -> None:
    """List the prompt records; the default is marked."""
    from ..classify import record

    for version in record.versions():
        typer.echo(f"{version}{'  (default)' if version == record.DEFAULT_VERSION else ''}")


@app.command("register")
def classify_register(
    prompt: Path = typer.Argument(..., exists=True, dir_okay=False),
    schema: Path = typer.Argument(..., exists=True, dir_okay=False),
    request_settings: Path = typer.Argument(..., exists=True, dir_okay=False),
) -> None:
    """Make a prompt record from draft files. Commit it before preparing a job with it."""
    from ..classify import record

    with reported_errors():
        version = record.register(prompt, schema, request_settings)
    typer.echo(f"{record.PROMPTS / version}: commit it, then use --prompt {version}")


@app.command("prepare")
def classify_prepare(
    job: str = typer.Option(..., help="A new name, or the name of a job to resume"),
    prompt: str | None = typer.Option(None, help="Prompt version; default: the default record"),
    cantons: str | None = typer.Option(None, help="Comma-separated canton codes, or all"),
    shas: Path | None = typer.Option(None, exists=True, help="A file with one sha256 per line"),
    workers: int = typer.Option(16, min=1, help="Documents rendered at once"),
) -> None:
    """Render the requests of the documents that have no answer for the prompt version yet."""
    import pymupdf

    from ..classify import jobs, record
    from ..classify.store import Store

    if not cantons and not shas:
        raise typer.BadParameter("name --cantons (a list, or all) or --shas")
    wanted = None if cantons in (None, "all") else {c.strip().upper() for c in cantons.split(",")}
    chosen = {line.strip() for line in shas.read_text().split()} if shas else None
    paths = _classify_paths()
    with reported_errors(), Store(paths.database) as store:
        loaded = record.load(prompt or record.DEFAULT_VERSION)
        record.require_committed(loaded)
        with jobs.exclusive(paths, loaded.version):
            store.freeze_renderer(loaded.version, f"pymupdf {pymupdf.__version__}")
            rows = jobs.read_catalogue(database_path(), wanted, chosen)
            counts = jobs.prepare(
                store, paths, loaded, job, rows, settings.raw_dir, min(workers, os.cpu_count() or 1)
            )
            usd = jobs.expected_usd(store, loaded, job)
    typer.echo(
        f"job {job}: {counts['rendered']} rendered, {counts['failed']} failed, expected USD {usd:.2f}"
    )


@app.command("drive")
def classify_drive(
    job: str = typer.Option(...),
    max_usd: float = typer.Option(..., help="Stop sending, and cancel what runs, at this spend"),
) -> None:
    """Send a prepared job and store its answers as they come back. Runs until all are back."""
    from ..classify import jobs, record
    from ..classify.batch_api import BatchAPI
    from ..classify.store import Store

    if settings.openai_api_key is None:
        raise typer.BadParameter("OPENAI_API_KEY is not set")
    paths = _classify_paths()
    with reported_errors(), Store(paths.database) as store:
        loaded = record.load(store.job_version(job))
        record.require_committed(loaded)
        api = BatchAPI.connect(settings.openai_api_key.get_secret_value())
        try:
            with jobs.exclusive(paths, loaded.version):
                jobs.drive(store, api, paths, loaded, job, max_usd)
        finally:
            api.close()


@app.command("status")
def classify_status(
    prompt: str | None = typer.Option(None, help="Prompt version; default: the default record"),
) -> None:
    """Answers, failures and cost so far for a prompt version."""
    import json

    from ..classify import jobs, record
    from ..classify.store import Store

    with reported_errors(), Store(settings.process_db) as store:
        summary = jobs.status(store, prompt or record.DEFAULT_VERSION)
    typer.echo(json.dumps(summary))


@app.command("import-ledger")
def classify_import_ledger(
    ledger: Path = typer.Argument(..., exists=True, dir_okay=False),
    frozen: Path | None = typer.Option(
        None, exists=True, dir_okay=False, help="The ledger's frozen.json, naming its renderer"
    ),
) -> None:
    """Copy the answers of a ledger from the first implementation into the processing database.
    The ledger is only read, and importing it again adds nothing."""
    import json

    from ..classify import jobs
    from ..classify.store import Store

    with reported_errors(), Store(settings.process_db) as store:
        counts = jobs.import_ledger(store, ledger, frozen)
    typer.echo(json.dumps(counts))
