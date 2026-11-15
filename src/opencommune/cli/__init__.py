"""The `opencommune` command. Each stage is idempotent and skips work whose output already exists.

One module per part: `crawl` (discovery and download), `configuration` (the commune list and the
registers), `database` (the main and the serving database, the full-text index), `classify` and
`text`. Logging is configured here, once, for every command.
"""

from __future__ import annotations

import logging

import typer

from . import classify, configuration, crawl, database, text

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


app.add_typer(database.app)
app.add_typer(crawl.app)
app.add_typer(configuration.app)
app.add_typer(classify.app, name="classify")
app.add_typer(text.app, name="text")
