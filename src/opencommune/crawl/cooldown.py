"""Durable per-host cooldowns for explicit long HTTP Retry-After responses."""

from __future__ import annotations

import datetime as dt
import fcntl
import hashlib
import json
import math
import os
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

from ..config import settings


class CooldownStateError(Exception):
    """A local cooldown record cannot be trusted; callers must not send the request."""


def _host(url: str) -> str:
    host = urlsplit(url).hostname
    if not host:
        raise ValueError("cooldown requires a URL with a host")
    return host.lower().rstrip(".").removeprefix("www.")


def _path(host: str) -> Path:
    name = hashlib.sha256(host.encode("utf-8")).hexdigest()
    return settings.data_dir / "discovery" / "host_cooldowns" / f"{name}.json"


def _read(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        raise CooldownStateError(f"unreadable host cooldown record: {path}") from exc
    try:
        finite_epoch = (
            isinstance(data, dict)
            and type(data.get("until_epoch")) in (int, float)
            and math.isfinite(data["until_epoch"])
        )
    except OverflowError:
        finite_epoch = False
    if (
        not finite_epoch
        or type(data.get("status")) is not int
        or not (data["status"] == 429 or 500 <= data["status"] <= 599)
        or not isinstance(data.get("host"), str)
        or not isinstance(data.get("until_utc"), str)
        or _path(data["host"]) != path
    ):
        raise CooldownStateError(f"invalid host cooldown record: {path}")
    return data


def active(url: str) -> dict | None:
    """Return a still-active record, reading the atomic file on every check."""
    record = _read(_path(_host(url)))
    return record if record and record["until_epoch"] > time.time() else None


def record(url: str, seconds: float, status: int) -> dict:
    """Keep the latest expiry across concurrent collectors and separate processes."""
    if not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("cooldown duration must be finite and positive")
    if status != 429 and not 500 <= status <= 599:
        raise ValueError("cooldown requires an HTTP 429 or 5xx status")
    host = _host(url)
    path = _path(host)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        previous = _read(path)
        until = time.time() + seconds
        if previous and previous["until_epoch"] >= until:
            return previous
        try:
            until_utc = dt.datetime.fromtimestamp(until, dt.UTC).isoformat()
        except (OverflowError, OSError, ValueError) as exc:
            raise ValueError("cooldown expiry is outside supported datetime range") from exc
        record = {"host": host, "until_epoch": until, "until_utc": until_utc, "status": status}
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", dir=path.parent, prefix=path.stem + ".", delete=False
            ) as file:
                temporary = Path(file.name)
                json.dump(record, file)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            temporary.replace(path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return record
