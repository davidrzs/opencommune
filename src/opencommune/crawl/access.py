"""Current source-access observations, separate from the verified commune register.

Only failures are retained. Success clears the same URL, never another source's restriction.
Old generic `robots` checkpoints are deliberately not imported.
"""

import datetime as dt
import fcntl
import hashlib
import json
import logging
import os
import threading
import time
from contextlib import contextmanager
from urllib.parse import urlsplit, urlunsplit

from ..config import settings

_lock = threading.Lock()
log = logging.getLogger(__name__)


def origin(url):
    p = urlsplit(url or "")
    return (p.hostname or "").lower().removeprefix("www.")


def directory():
    return settings.data_dir / "discovery" / "access"


@contextmanager
def locked():
    directory().mkdir(parents=True, exist_ok=True)
    with _lock, (directory() / ".lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def record(url, status, *, rule=None, user_agent=None, channel="robots"):
    """Never let diagnostic persistence interrupt collection; do not store credentials."""
    p = urlsplit(url)
    if p.scheme not in {"http", "https"} or not p.hostname or p.username or p.password:
        return
    url = urlunsplit((p.scheme, p.netloc, p.path or "/", p.query, ""))
    path = directory() / (hashlib.sha256((channel + url).encode()).hexdigest() + ".json")
    if status == "ok" and not path.exists():
        return
    try:
        with locked():
            if status == "ok":
                path.unlink(missing_ok=True)
                return
            path.parent.mkdir(parents=True, exist_ok=True)
            previous = json.loads(path.read_text()) if path.exists() else {}
            now = dt.datetime.now(dt.UTC).isoformat()
            # A failed recheck does not prove an earlier restriction has been lifted.
            confirmed = now if status == "restricted" else previous.get("restricted_at")
            row = dict(
                url=url,
                channel=channel,
                status=status,
                checked_at=now,
                robots_url=f"{p.scheme}://{p.netloc}/robots.txt",
                rule=rule if status == "restricted" else previous.get("rule"),
                restricted_at=confirmed,
                user_agent=user_agent,
            )
            temp = path.with_suffix(f".{os.getpid()}.tmp")
            temp.write_text(json.dumps(row))
            temp.replace(path)
    except (OSError, ValueError):
        log.warning("Could not persist source access observation", exc_info=True)


def observations():
    rows = []
    for path in directory().glob("*.json"):
        try:
            row = json.loads(path.read_text())
            if row.get("status") in {
                "restricted",
                "rate_limited",
                "robots_unavailable",
                "technical_error",
            }:
                rows.append(row)
        except (OSError, ValueError):
            continue
    return rows


def by_commune(register):
    """The observations summarised per commune and website, newest check first: one row per host
    with the latest check's status and the last confirmed restriction. Rows link to the website,
    never to a document. A host counts only when exactly one register commune has its website
    there."""
    owners = {}
    for e in register:
        if e.website:
            owners.setdefault(origin(e.website), set()).add(e.bfs_id)
    sites = {}
    for o in sorted(observations(), key=lambda o: o["checked_at"]):
        ids = owners.get(origin(o["url"]), set())
        if len(ids) != 1:
            continue
        key = (next(iter(ids)), origin(o["url"]))
        p = urlsplit(o["url"])
        earlier = sites.get(key, {}).get("restricted_at")
        sites[key] = dict(
            source_url=f"{p.scheme}://{p.netloc}/",
            status=o["status"],
            checked_at=o["checked_at"],
            robots_url=o["robots_url"],
            restricted_at=max(filter(None, (o.get("restricted_at"), earlier)), default=None),
        )
    rows = {}
    for (bfs_id, _), site in sorted(
        sites.items(), key=lambda kv: kv[1]["checked_at"], reverse=True
    ):
        rows.setdefault(bfs_id, []).append(site)
    return rows


def stale(site):
    """A site whose last restriction or check is a week old or more is shown as stale."""
    seen = dt.datetime.fromisoformat(site["restricted_at"] or site["checked_at"])
    return dt.datetime.now(dt.UTC) - seen >= dt.timedelta(days=7)


def checkpoint_candidates():
    """Old failures are leads for fresh checks, never evidence for the public map."""
    seen = set()
    for family in ("iweb", "linked_archive", "wordpress"):
        for path in sorted((settings.data_dir / "discovery" / family).glob("*.json")):
            try:
                state = json.loads(path.read_text())
                for section in ("pages", "downloads"):
                    for url, value in state.get(section, {}).items():
                        if value.get("kind") == "robots" and url not in seen:
                            seen.add(url)
                            yield dict(url=url, channel="robots", checked_at="")
            except (OSError, ValueError, AttributeError):
                continue


def recheck(limit=100, seed_checkpoints=False):
    """Recheck oldest observed paths, without downloading PDFs, using normal politeness."""
    from .http import FetchFailure, Politeness, _send, make_client

    rows = list(checkpoint_candidates()) if seed_checkpoints else observations()
    rows = sorted(rows, key=lambda r: r["checked_at"])[:limit]
    deadline = time.monotonic() + 600
    # Runs under the same download-job lock as collection.
    with make_client() as client:
        polite = Politeness(client, max(2, settings.request_delay_seconds), settings.ua)
        for row in rows:
            if time.monotonic() >= deadline:
                break
            if polite.allowed(row["url"]) and row.get("channel") == "request":
                try:
                    response = _send(
                        client, polite, client.build_request("GET", row["url"]), stream=True
                    )
                    response.close()  # Check availability without downloading the body.
                except FetchFailure:
                    pass
