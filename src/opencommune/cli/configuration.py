"""The checked-in configuration: the commune list (`lint-communes`), the BFS commune register
snapshot (`bfs-sync`) and the coverage register (`register check`)."""

from __future__ import annotations

from pathlib import Path

import typer

app = typer.Typer()


@app.command("bfs-sync")
def bfs_sync() -> None:
    """Download the BFS commune register snapshot and check communes.yaml against it."""
    from ..communes import bfs_communes, ensure_bfs_snapshot, load_communes
    from ..crawl.fetch import fetch_text

    ensure_bfs_snapshot(fetch_text)
    register = bfs_communes()
    typer.echo(f"register: {len(register)} communes")
    for c in load_communes():
        official = register.get(c.bfs_id)
        mark = "ok " if official and official.split(" (")[0] == c.name else "?? "
        typer.echo(f"  {mark}{c.bfs_id:>5}  {c.name:<20} register: {official}")


register_app = typer.Typer(no_args_is_help=True, help="The coverage register in data/register/.")
app.add_typer(register_app, name="register")


@register_app.command("check")
def register_check(
    register_dir: Path | None = typer.Option(None, help="Directory of the <CANTON>.yaml files"),
    communes: Path | None = typer.Option(None, help="communes.yaml to check against"),
) -> None:
    """Check the register against communes.yaml and the BFS snapshot; exit 1 with the problems."""
    from ..communes import bfs_register, load_communes
    from ..register import check, read_register_files

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
    from ..communes import bfs_register, read_commune_items
    from ..lint import lint_communes

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
