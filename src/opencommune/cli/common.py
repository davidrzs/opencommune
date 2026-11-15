"""Helpers shared by the command modules."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import typer

from ..config import settings

NAME = re.compile(r"[a-z0-9][a-z0-9._-]*")


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


def named(directory: Path, name: str) -> Path:
    """`directory / name` for the name of a pass or queue: lower-case letters, digits, '.', '_'
    and '-', so it never leaves the directory."""
    if not NAME.fullmatch(name):
        raise typer.BadParameter(f"{name!r}: lower-case letters, digits, '.', '_' and '-' only")
    return directory / name


def file_sha256(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
