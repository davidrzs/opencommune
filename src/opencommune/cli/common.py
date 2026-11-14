"""Helpers shared by the command modules."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import typer

from ..config import settings


@contextmanager
def reported_errors() -> Iterator[None]:
    try:
        yield
    except (RuntimeError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from None


def database_path() -> Path:
    from sqlalchemy.engine import make_url

    return Path(make_url(settings.database_url).database)
