"""Command-line entry point. Each stage is idempotent and skips work whose output already exists."""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import typer

from .config import settings

app = typer.Typer(
    no_args_is_help=True, add_completion=False, help="OpenCommune crawler and database build."
)


@app.callback()
def _root(verbose: bool = typer.Option(False, "--verbose", "-v")) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


@app.command("init-db")
def init_db_cmd() -> None:
    """Create the SQLite database, tables, and the FTS5 index."""
    from .db import init_db

    settings.ensure_dirs()
    init_db()
    typer.echo(f"database ready at {settings.database_url}")


def _communes(bfs_ids: str | None, only_new: bool = False, source: str | None = None):
    """Select communes by a comma-separated list of BFS ids, or those without any fetched document.
    With `source`, "new" means no document fetched through that adapter yet, and communes without
    such a source are left out."""
    from .communes import load_communes

    communes = load_communes()
    if bfs_ids:
        wanted = {int(x) for x in bfs_ids.split(",") if x.strip()}
        communes = [c for c in communes if c.bfs_id in wanted]
        missing = wanted - {c.bfs_id for c in communes}
        if missing:
            raise typer.BadParameter(
                f"no commune with bfs_id {sorted(missing)} in the configuration"
            )
    if source:
        communes = [c for c in communes if any(s.adapter == source for s in c.all_sources())]
    if only_new:
        from .crawl.store import load_index

        primary = {c.bfs_id: c.adapter for c in communes}
        seen = {
            v.get("commune_bfs_id")
            for v in load_index().values()
            if source is None
            or (v.get("adapter") or primary.get(v.get("commune_bfs_id"))) == source
        }
        communes = [c for c in communes if c.bfs_id not in seen]
    return communes


@app.command()
def fetch(
    commune: str | None = typer.Option(None, help="BFS id, or several separated by commas"),
    limit: int | None = typer.Option(None, help="Max documents per commune and source"),
    dry_run: bool = typer.Option(False, help="List discovered documents without downloading"),
    max_follow: int | None = typer.Option(
        None, min=1, help="Cap pages followed per hop for a small initial fetch"
    ),
    only_new: bool = typer.Option(False, help="Only communes without any fetched document yet"),
    source: str | None = typer.Option(
        None, help="Only sources of this adapter, for example wp_media"
    ),
    rebuild_index: bool = typer.Option(
        False, help="Rewrite data/raw/urls.jsonl from the sidecars, then stop"
    ),
) -> None:
    """Discover and download public municipal documents into data/raw/."""
    from .crawl import fetch as fetch_stage
    from .crawl import store

    if rebuild_index:
        from .communes import load_communes

        volatile = {
            c.bfs_id: [p for s in c.all_sources() for p in s.adapter_config.volatile_params]
            for c in load_communes()
        }
        typer.echo(f"{len(store.rebuild_index(volatile))} URLs in {store.index_path()}")
        return
    for res in fetch_stage.run(
        _communes(commune, only_new, source),
        limit=limit,
        dry_run=dry_run,
        source_adapter=source,
        max_follow=max_follow,
    ):
        typer.echo(
            f"{res.commune.name} ({res.commune.canton}): {len(res.discovered)} discovered, "
            f"{len(res.downloaded)} downloaded, {len(res.skipped)} known, {len(res.errors)} errors"
        )
        for run in res.runs:
            if run.listing != "ok":
                typer.echo(f"    listing {run.listing} ({run.source.adapter})")
        for d in res.discovered:
            typer.echo(f"    {d.date or '   ?    '}  {d.title[:60]:<60}  {d.url}")
        for e in res.errors:
            typer.echo(f"    ERROR {e}")


@app.command("iweb")
def iweb_command(
    mode: str = typer.Argument(..., help="discover, fetch, sync, or report"),
    commune: str | None = typer.Option(
        None, help="BFS ids; defaults to all i-web register entries"
    ),
    page_budget: int = typer.Option(
        100, min=1, help="Pages per commune this pass; unfinished queues are retained"
    ),
    limit: int | None = typer.Option(
        None, min=1, help="Download attempts per commune; known PDFs do not count"
    ),
    retry_failed: bool = typer.Option(False, help="Retry previously failed pages or documents"),
    refresh: bool = typer.Option(
        False, help="Revisit listing pages to find new publications; keep held PDFs"
    ),
    only_unconfigured: bool = typer.Option(False, help="Discover communes not yet configured"),
    max_minutes: int | None = typer.Option(
        None, min=1, help="Stop between requests after this time; retain progress"
    ),
) -> None:
    """Inventory the i-web sites and download their PDFs, resumably."""
    from .communes import load_communes
    from .crawl import iweb
    from .register import load_register

    if mode not in {"discover", "fetch", "sync", "report"}:
        raise typer.BadParameter("mode must be discover, fetch, sync, or report")
    entries = [r for r in load_register() if r.vendor == "i-web" and r.website]
    if commune:
        try:
            wanted = [int(x.strip()) for x in commune.split(",") if x.strip()]
        except ValueError:
            raise typer.BadParameter("commune must contain comma-separated BFS ids") from None
        by_id = {r.bfs_id: r for r in entries}
        if missing := set(wanted) - by_id.keys():
            raise typer.BadParameter(
                f"not an i-web register entry with a website: {sorted(missing)}"
            )
        entries = [by_id[n] for n in dict.fromkeys(wanted)]
    if only_unconfigured:
        entries = [r for r in entries if r.status != "configured"]
    if mode == "report":
        import json

        for entry in entries:
            state = iweb.read(entry.bfs_id)
            typer.echo(
                json.dumps(
                    iweb.summary(state)
                    if state
                    else {"bfs_id": entry.bfs_id, "name": entry.name, "status": "not_started"},
                    ensure_ascii=False,
                )
            )
        return
    try:
        iweb.run(
            entries,
            mode=mode,
            communes=load_communes(),
            page_budget=page_budget,
            limit=limit,
            retry_failed=retry_failed,
            refresh=refresh,
            max_minutes=max_minutes,
            emit=typer.echo,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from None
    if mode in {"fetch", "sync"}:
        catalog_command()


@app.command("wordpress")
def wordpress_command(
    mode: str = typer.Argument(..., help="configure, fetch or check"),
    commune: str | None = typer.Option(None, help="Optional comma-separated BFS ids"),
    limit: int | None = typer.Option(None, min=1, help="New PDF attempts per commune"),
    max_minutes: int | None = typer.Option(
        None, min=1, help="Stop between requests; retain progress"
    ),
    commune_max_minutes: float | None = typer.Option(
        None, min=0.01, help="Cooperative time slice per commune in minutes"
    ),
    workers: int = typer.Option(1, min=1, max=8, help="Concurrent commune downloads"),
    retry_failed: bool = typer.Option(False),
    refresh: bool = typer.Option(False),
):
    """Configure, fetch or check the WordPress archives (data/archive-sources.yaml)."""
    from .communes import bfs_register
    from .crawl import wordpress

    if mode not in {"configure", "fetch", "check"}:
        raise typer.BadParameter("mode must be configure, fetch or check")
    try:
        if mode == "configure":
            import json

            from .crawl.archive_config import configure_wordpress

            typer.echo(json.dumps(configure_wordpress(), ensure_ascii=False))
            return
        sources = wordpress.load_sources()
        if commune:
            wanted = {int(n.strip()) for n in commune.split(",")}
            if wanted - {s.bfs_id for s in sources}:
                raise ValueError("BFS id missing from archive-sources.yaml")
            sources = [s for s in sources if s.bfs_id in wanted]
        # only the sources this run uses: an entry under review elsewhere does not block a list
        wordpress.validate_sources(sources, snapshot_optional=mode == "check")
        if mode == "check":
            where = "with" if bfs_register() else "without"
            typer.echo(
                f"{len(sources)} WordPress archive sources valid, checked {where} the BFS snapshot"
            )
            return
        wordpress.run_fetch(
            sources,
            limit=limit,
            max_minutes=max_minutes,
            commune_max_minutes=commune_max_minutes,
            retry_failed=retry_failed,
            refresh=refresh,
            workers=workers,
            emit=typer.echo,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from None
    catalog_command()


@app.command("linked-archive")
def linked_archive_command(
    mode: str = typer.Argument(..., help="fetch or check"),
    commune: str | None = typer.Option(None, help="Optional comma-separated BFS ids"),
    limit: int = typer.Option(3, min=1, help="New PDF attempts per commune"),
    max_minutes: int = typer.Option(60, min=1),
    commune_max_minutes: float | None = typer.Option(
        None, min=0.01, help="Cooperative time slice per commune in minutes"
    ),
    refresh: bool = typer.Option(False, help="Read the configured listings again"),
    workers: int = typer.Option(1, min=1, max=8, help="Concurrent commune downloads"),
    retry_failed: bool = typer.Option(False),
):
    """Fetch or check the linked archives (data/linked-sources.yaml)."""
    from .communes import bfs_register
    from .crawl import linked_archive

    if mode not in {"fetch", "check"}:
        raise typer.BadParameter("mode must be fetch or check")
    try:
        sources = linked_archive.load_sources()
        if commune:
            wanted = {int(n.strip()) for n in commune.split(",")}
            if wanted - {s.bfs_id for s in sources}:
                raise ValueError("BFS id missing from linked-sources.yaml")
            sources = [s for s in sources if s.bfs_id in wanted]
        # only the sources this run uses: an entry under review elsewhere does not block a list
        sources = linked_archive.validate_sources(sources, snapshot_optional=mode == "check")
        if mode == "check":
            where = "with" if bfs_register() else "without"
            typer.echo(
                f"{len(sources)} linked archive sources valid, checked {where} the BFS snapshot"
            )
            return
        linked_archive.run_fetch(
            sources,
            limit=limit,
            max_minutes=max_minutes,
            commune_max_minutes=commune_max_minutes,
            refresh=refresh,
            retry_failed=retry_failed,
            workers=workers,
            emit=typer.echo,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from None
    catalog_command()


@app.command("bfs-sync")
def bfs_sync() -> None:
    """Download the BFS commune register snapshot and check communes.yaml against it."""
    from .communes import bfs_communes, ensure_bfs_snapshot, load_communes
    from .crawl.fetch import fetch_text

    ensure_bfs_snapshot(fetch_text)
    register = bfs_communes()
    typer.echo(f"register: {len(register)} communes")
    for c in load_communes():
        official = register.get(c.bfs_id)
        mark = "ok " if official and official.split(" (")[0] == c.name else "?? "
        typer.echo(f"  {mark}{c.bfs_id:>5}  {c.name:<20} register: {official}")


def _database_path() -> Path:
    from sqlalchemy.engine import make_url

    return Path(make_url(settings.database_url).database)


@app.command()
def build() -> None:
    """Write the serving tables the web server reads (register, access observations), from scratch."""
    from . import build as stage

    for table, rows in stage.run(_database_path()).items():
        typer.echo(f"{table}: {rows} rows")


register_app = typer.Typer(no_args_is_help=True, help="The coverage register in data/register/.")
app.add_typer(register_app, name="register")


@register_app.command("check")
def register_check(
    register_dir: Path | None = typer.Option(None, help="Directory of the <CANTON>.yaml files"),
    communes: Path | None = typer.Option(None, help="communes.yaml to check against"),
) -> None:
    """Check the register against communes.yaml and the BFS snapshot; exit 1 with the problems."""
    from .communes import bfs_register, load_communes
    from .register import check, read_register_files

    try:
        files = read_register_files(register_dir)
    except ValueError as exc:
        typer.echo(f"register does not validate: {exc}")
        raise typer.Exit(code=1) from exc
    entries = sorted((e for _, rows in files for e in rows), key=lambda e: (e.canton, e.bfs_id))
    bfs = bfs_register() or None
    problems = check(entries, load_communes(communes), bfs, files)
    for p in problems:
        typer.echo(f"  {p}")
    where = "with" if bfs else "without"
    typer.echo(
        f"register: {len(entries)} rows in {len(files)} files, checked {where} the BFS snapshot: {len(problems)} problems"
    )
    if problems:
        raise typer.Exit(code=1)


@app.command("lint-communes")
def lint_communes_cmd(
    path: Path | None = typer.Option(
        None, help="A communes.yaml to check; default: data/communes.yaml"
    ),
) -> None:
    """Check the commune configuration: schema, regexes, selectors, adapters, BFS ids, vocabularies,
    coordinates, order; exit 1 with the problems."""
    from .communes import bfs_register, read_commune_items
    from .lint import lint_communes

    bfs = bfs_register() or None
    problems = lint_communes(path, bfs)
    for p in problems:
        typer.echo(f"  {p}")
    files = read_commune_items(path)
    n = sum(len(items) for _, items in files)
    where = "with" if bfs else "without"
    typer.echo(
        f"lint-communes: {n} entries in {len(files)} file(s), checked {where} the BFS snapshot: "
        f"{len(problems)} problems"
    )
    if problems:
        raise typer.Exit(code=1)


@app.command("catalog")
def catalog_command():
    """Refresh the website's document catalogue from the crawl records."""
    import fcntl

    from . import catalog
    from .communes import load_communes
    from .db import init_db, session_scope

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    with (settings.data_dir / "catalog.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            typer.echo("catalogue refresh already running")
            return
        init_db()
        communes = load_communes()
        with session_scope() as session:
            catalog.upsert_communes(session, communes)
        with session_scope() as session:
            count = catalog.refresh(session, communes)
        typer.echo(f"{count} PDFs in the catalogue")
        pages = catalog.html_documents()
        if pages:
            typer.echo(f"{pages} HTML decision pages (not in the catalogue)")


@app.command("storage-check")
def storage_check() -> None:
    """Exit 1 when the raw archive's filesystem is below its free-space reserve."""
    from .crawl.storage import StorageReserveError, require_space

    try:
        free = require_space()
    except (StorageReserveError, OSError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from None
    typer.echo(f"{free:,} bytes free, reserve {settings.raw_min_free_bytes:,}")


@app.command("access-recheck")
def access_recheck(
    limit: int = typer.Option(100, min=0, help="Observations to recheck, oldest first"),
    seed_checkpoints: bool = typer.Option(
        False, help="Start from robots refusals recorded in the collectors' checkpoints"
    ),
) -> None:
    """Recheck the oldest access failures (robots.txt, rate limits, errors) without downloading."""
    from .crawl import access

    access.recheck(limit, seed_checkpoints)


@app.command("coverage-report")
def coverage_report(
    output: Path = typer.Option(..., help="Directory for coverage.json and coverage.md"),
    shallow_limit: int = typer.Option(
        10, min=0, help="Communes with at most this many PDFs count as shallow"
    ),
) -> None:
    """Report how deep the archive goes per commune; reads the database and the crawl state."""
    import json

    from .crawl import coverage_report as report

    try:
        summary = report.write(output, shallow_limit)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from None
    typer.echo(json.dumps(summary, ensure_ascii=False))


classify_app = typer.Typer(
    no_args_is_help=True,
    help="Classify documents with a language model, through OpenAI's Batch API.",
)
app.add_typer(classify_app, name="classify")


@contextmanager
def _reported_errors() -> Iterator[None]:
    try:
        yield
    except (RuntimeError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from None


def _classify_paths():
    from .classify.jobs import Paths

    return Paths(settings.process_db, settings.batch_outputs_dir, settings.scratch)


@classify_app.command("prompts")
def classify_prompts() -> None:
    """List the prompt records; the default is marked."""
    from .classify import record

    for version in record.versions():
        typer.echo(f"{version}{'  (default)' if version == record.DEFAULT_VERSION else ''}")


@classify_app.command("register")
def classify_register(
    prompt: Path = typer.Argument(..., exists=True, dir_okay=False),
    schema: Path = typer.Argument(..., exists=True, dir_okay=False),
    request_settings: Path = typer.Argument(..., exists=True, dir_okay=False),
) -> None:
    """Make a prompt record from draft files. Commit it before preparing a job with it."""
    from .classify import record

    with _reported_errors():
        version = record.register(prompt, schema, request_settings)
    typer.echo(f"{record.PROMPTS / version}: commit it, then use --prompt {version}")


@classify_app.command("prepare")
def classify_prepare(
    job: str = typer.Option(..., help="A new name, or the name of a job to resume"),
    prompt: str | None = typer.Option(None, help="Prompt version; default: the default record"),
    cantons: str | None = typer.Option(None, help="Comma-separated canton codes, or all"),
    shas: Path | None = typer.Option(None, exists=True, help="A file with one sha256 per line"),
    workers: int = typer.Option(16, min=1, help="Documents rendered at once"),
) -> None:
    """Render the requests of the documents that have no answer for the prompt version yet."""
    import pymupdf

    from .classify import jobs, record
    from .classify.store import Store

    if not cantons and not shas:
        raise typer.BadParameter("name --cantons (a list, or all) or --shas")
    wanted = None if cantons in (None, "all") else {c.strip().upper() for c in cantons.split(",")}
    chosen = {line.strip() for line in shas.read_text().split()} if shas else None
    paths = _classify_paths()
    with _reported_errors(), Store(paths.database) as store:
        loaded = record.load(prompt or record.DEFAULT_VERSION)
        record.require_committed(loaded)
        with jobs.exclusive(paths, loaded.version):
            store.freeze_renderer(loaded.version, f"pymupdf {pymupdf.__version__}")
            rows = jobs.read_catalogue(_database_path(), wanted, chosen)
            counts = jobs.prepare(
                store, paths, loaded, job, rows, settings.raw_dir, min(workers, os.cpu_count() or 1)
            )
            usd = jobs.expected_usd(store, loaded, job)
    typer.echo(
        f"job {job}: {counts['rendered']} rendered, {counts['failed']} failed, expected USD {usd:.2f}"
    )


@classify_app.command("drive")
def classify_drive(
    job: str = typer.Option(...),
    max_usd: float = typer.Option(..., help="Stop sending, and cancel what runs, at this spend"),
) -> None:
    """Send a prepared job and store its answers as they come back. Runs until all are back."""
    from .classify import jobs, record
    from .classify.batch_api import BatchAPI
    from .classify.store import Store

    if settings.openai_api_key is None:
        raise typer.BadParameter("OPENAI_API_KEY is not set")
    paths = _classify_paths()
    with _reported_errors(), Store(paths.database) as store:
        loaded = record.load(store.job_version(job))
        record.require_committed(loaded)
        api = BatchAPI.connect(settings.openai_api_key.get_secret_value())
        try:
            with jobs.exclusive(paths, loaded.version):
                jobs.drive(store, api, paths, loaded, job, max_usd)
        finally:
            api.close()


@classify_app.command("status")
def classify_status(
    prompt: str | None = typer.Option(None, help="Prompt version; default: the default record"),
) -> None:
    """Answers, failures and cost so far for a prompt version."""
    import json

    from .classify import jobs, record
    from .classify.store import Store

    with _reported_errors(), Store(settings.process_db) as store:
        summary = jobs.status(store, prompt or record.DEFAULT_VERSION)
    typer.echo(json.dumps(summary))


@classify_app.command("import-ledger")
def classify_import_ledger(
    ledger: Path = typer.Argument(..., exists=True, dir_okay=False),
    frozen: Path | None = typer.Option(
        None, exists=True, dir_okay=False, help="The ledger's frozen.json, naming its renderer"
    ),
) -> None:
    """Copy the answers of a ledger from the first implementation into the processing database.
    The ledger is only read, and importing it again adds nothing."""
    import json

    from .classify import jobs
    from .classify.store import Store

    with _reported_errors(), Store(settings.process_db) as store:
        counts = jobs.import_ledger(store, ledger, frozen)
    typer.echo(json.dumps(counts))


if __name__ == "__main__":
    app()
