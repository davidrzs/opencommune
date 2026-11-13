"""Resumable mixed-PDF archives from verified WordPress media endpoints.

Configuration is tracked separately from the human publication register. Inventories
and download observations are machine state; neither body nor upload date is inferred.
"""

from __future__ import annotations

import datetime as dt
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Literal
from urllib.parse import unquote, urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..communes import bfs_register
from ..config import settings
from ..register import load_register
from ..schemas import AdapterStep, DocumentLink
from . import fetch, http, scheduling, storage, store
from .adapters.wp_media import WpMediaAdapter
from .checkpoints import Checkpoints
from .iweb import clean_url, same_site

ADAPTER = WpMediaAdapter()
STEP = AdapterStep(selector="media")


class ArchiveSourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bfs_id: int
    website: str
    adapter: Literal["wp_media"] = "wp_media"
    listing_url: str
    document_url_prefixes: list[str] = Field(default_factory=list)
    attribution_note: str = ""

    @field_validator("website", "listing_url")
    @classmethod
    def public_url(cls, value):
        if clean_url(value) is None:
            raise ValueError("expected an HTTP(S) URL without credentials")
        return value

    @model_validator(mode="after")
    def endpoint_on_site(self):
        if not same_site(self.website, self.listing_url):
            raise ValueError("listing endpoint must belong to the configured website")
        if not urlsplit(self.listing_url).path.rstrip("/").endswith("/wp-json/wp/v2/media"):
            raise ValueError("expected a WordPress media endpoint")
        for prefix in self.document_url_prefixes:
            parts = urlsplit(prefix)
            segments = unquote(parts.path).split("/")
            if (
                clean_url(prefix) is None
                or parts.query
                or parts.fragment
                or not parts.path.endswith("/")
                or parts.path == "/"
                or any(segment in {".", ".."} for segment in segments)
                or not self.attribution_note.strip()
            ):
                raise ValueError(
                    "document prefixes require a directory path and an attribution note"
                )
        return self

    def allows_document(self, url: str) -> bool:
        if clean_url(url) is None:
            return False
        if same_site(url, self.website):
            return True
        parts = urlsplit(url)
        if any(segment in {".", ".."} for segment in unquote(parts.path).split("/")):
            return False
        return any(
            parts.scheme == urlsplit(prefix).scheme
            and parts.netloc == urlsplit(prefix).netloc
            and parts.path.startswith(urlsplit(prefix).path)
            for prefix in self.document_url_prefixes
        )


def load_sources(path: Path | None = None) -> list[ArchiveSourceConfig]:
    path = path or settings.config_root / "archive-sources.yaml"
    if not path.exists():
        return []
    items = yaml.safe_load(path.read_text()) or []
    if not isinstance(items, list):
        raise ValueError("archive sources must be a list")
    sources = [ArchiveSourceConfig.model_validate(item) for item in items]
    if len({s.bfs_id for s in sources}) != len(sources):
        raise ValueError("duplicate archive source BFS ID")
    return sources


def validate_sources(configs, entries=None, *, snapshot_optional=False):
    """Reject stale or ambiguous tracked attribution before making any requests. A crawl needs the
    BFS snapshot; with `snapshot_optional`, a check without it (no data directory, as in CI) skips
    the identity comparison."""
    sources = [ArchiveSourceConfig.model_validate(c) for c in configs]
    register = {e.bfs_id: e for e in (load_register() if entries is None else entries)}
    identities = bfs_register()
    compare = bool(identities) or not snapshot_optional
    if len({c.bfs_id for c in sources}) != len(sources):
        raise ValueError("duplicate archive source BFS ID")
    for source in sources:
        entry = register.get(source.bfs_id)
        identity = identities.get(source.bfs_id)
        if (
            entry is None
            or (compare and (identity is None or identity[1] != entry.canton))
            or entry.vendor != "wordpress"
            or not entry.website
            or not same_site(entry.website, source.website)
        ):
            raise ValueError(f"{source.bfs_id}: registry or website mismatch; review required")
    return sources


CHECKPOINTS = Checkpoints("wordpress", "WordPress archive")
directory, read, save, locked = (
    CHECKPOINTS.directory,
    CHECKPOINTS.read,
    CHECKPOINTS.save,
    CHECKPOINTS.locked,
)


def summary(state):
    downloads = list(state["downloads"].values())
    return {
        "bfs_id": state["bfs_id"],
        "name": state["name"],
        "status": state["status"],
        "pages": len(state["pages"]),
        "pending_pages": len(state["pending"]),
        "document_candidates": len(state["documents"]),
        "held_urls": sum(d["status"] == "held" for d in downloads),
        "failed_downloads": sum(d["status"] == "failed" for d in downloads),
        "review_documents": len(state["review_documents"]),
        "review_items": sum(len(items) for items in state.get("review_items", {}).values()),
    }


def fetch_one(
    config,
    entry,
    client,
    polite,
    index,
    *,
    limit=None,
    deadline=None,
    retry_failed=False,
    refresh=False,
):
    """Inventory one page at a time, downloading before advancing pagination."""
    first = ADAPTER.listing_urls(SimpleNamespace(listing_urls=[config.listing_url]))[0]
    state = read(config.bfs_id) or {
        "version": 1,
        "bfs_id": config.bfs_id,
        "name": entry.name if entry else "",
        "canton": entry.canton if entry else "",
        "website": config.website,
        "endpoint": config.listing_url,
        "pending": [first],
        "pages": {},
        "documents": {},
        "downloads": {},
        "review_documents": {},
        "status": "pending",
    }
    if refresh:
        # A failed or short refresh still gets a turn in the rotation.
        state["refresh_attempted_at"] = dt.datetime.now(dt.UTC).isoformat()
    identity = bfs_register().get(config.bfs_id)
    if (
        entry is None
        or identity is None
        or identity[1] != entry.canton
        or entry.vendor != "wordpress"
        or not entry.website
        or not same_site(entry.website, config.website)
        or state["website"] != config.website
        or state["endpoint"] != config.listing_url
        or state["canton"] != entry.canton
    ):
        state.update(status="review", reason="registry_or_source_changed")
        save(state)
        return state
    # Canonical registry name is independent of potentially stale machine observations.
    state["name"] = identity[0]
    commune = SimpleNamespace(
        bfs_id=entry.bfs_id, name=identity[0], canton=entry.canton, body="unknown"
    )
    if refresh:
        state.update(pending=[first], pages={})
        state["refreshed_at"] = dt.datetime.now(dt.UTC).isoformat()
    # the reason is stored with excluded documents in existing checkpoints: keep it as it is
    listing_scoped = http.Scoped(
        polite,
        lambda url: clean_url(url) is not None and same_site(url, config.website),
        "external URL requires review",
    )
    document_scoped = http.Scoped(polite, config.allows_document, "external URL requires review")
    newly_allowed = [
        url
        for url, reason in state["review_documents"].items()
        if reason in {"external_document", "external URL requires review"}
        and config.allows_document(url)
    ]
    for url in newly_allowed:
        state["review_documents"].pop(url)
    if any(url not in state["documents"] for url in newly_allowed):
        # Older inventories recorded excluded API items only by URL, without a listing.
        # Revisit the API to recover their source metadata and attribution.
        state.update(pending=[first], pages={})
    attempted = 0
    attempted_urls = set()
    stopped = False
    state["status"] = "running"
    while not stopped:
        for url, doc in state["documents"].items():
            if deadline is not None and time.monotonic() >= deadline:
                stopped = True
                break
            known = index.get(store.canonical_url(url))
            if known and store.held(known["sha256"]):
                state["downloads"][url] = {"status": "held", "sha256": known["sha256"]}
                continue
            if url in state["review_documents"] or url in attempted_urls:
                continue
            previous = state["downloads"].get(url, {})
            retry_at = previous.get("retry_at")
            if retry_at is not None and time.time() < retry_at:
                continue
            if (
                previous.get("status") in {"failed", "not_pdf"}
                and not retry_failed
                and retry_at is None
            ):
                continue
            if limit is not None and attempted >= limit:
                stopped = True
                break
            attempted += 1
            attempted_urls.add(url)
            try:
                store._download(
                    DocumentLink.model_validate(doc), commune, client, document_scoped, index
                )
            except http.FetchFailure as exc:
                if exc.kind == "external":
                    state["review_documents"][url] = exc.message
                else:
                    state["downloads"][url] = {
                        "status": "not_pdf" if exc.kind == "not_pdf" else "failed",
                        "kind": exc.kind,
                        "message": exc.message,
                    }
                    if exc.retry_at is not None:
                        state["downloads"][url]["retry_at"] = exc.retry_at
                if exc.kind == "robots" or exc.status == 429 or exc.retry_at is not None:
                    stopped = True
            else:
                state["downloads"][url] = {
                    "status": "held",
                    "sha256": index[store.canonical_url(url)]["sha256"],
                }
            save(state)
            if stopped:
                break
        if stopped or (limit is not None and attempted >= limit):
            break
        if deadline is not None and time.monotonic() >= deadline:
            break
        if not state["pending"]:
            all_held = all(
                state["downloads"].get(url, {}).get("status") == "held"
                for url in state["documents"]
            )
            state["status"] = "complete" if all_held else "pending"
            break
        url = state["pending"][0]
        try:
            if not listing_scoped.allowed(url):
                raise http.FetchFailure("robots", url, "disallowed by robots.txt")
            response = http._send(
                client, listing_scoped, fetch._build_request(ADAPTER, STEP, url, client)
            )
            http._ensure_ok(response, url)
            items = response.json()
            if not isinstance(items, list):
                raise ValueError("media endpoint did not return an array of records")
            valid = []
            rejected = []
            for position, item in enumerate(items):
                if (
                    not isinstance(item, dict)
                    or not isinstance(item.get("source_url"), str)
                    or (item.get("title") is not None and not isinstance(item["title"], dict))
                ):
                    # A restricted attachment can appear as an error object among public
                    # records. Record the gap, never follow its links, and keep usable rows.
                    rejected.append(
                        {
                            "position": position,
                            "reason": str(item.get("code", "invalid_media_record"))
                            if isinstance(item, dict)
                            else "invalid_media_record",
                        }
                    )
                    continue
                valid.append(item)
            state.setdefault("review_items", {})[url] = rejected
            links = ADAPTER.extract_links(json.dumps(valid), str(response.url), STEP, None, "dmy")
            for link in links:
                if not config.allows_document(link.url):
                    state["review_documents"][link.url] = "external_document"
                    continue
                doc = DocumentLink(
                    url=link.url,
                    title=link.text,
                    date=link.date,
                    date_precision=link.date_precision,
                    body="unknown",
                    listing_url=url,
                    adapter="wp_media",
                    upstream_id=link.upstream_id,
                )
                state["documents"].setdefault(link.url, doc.model_dump(mode="json"))
            following = ADAPTER.next_url(response.text, url, STEP, response.headers)
        except (http.FetchFailure, ValueError, TypeError, KeyError) as exc:
            state.update(status="listing_error", error=str(exc))
            save(state)  # Retain the pending URL so a later run can retry it.
            break
        state["pages"][url] = {"documents": len(links), "status": "ok"}
        state["pending"].pop(0)
        if following:
            if following in state["pages"]:
                state.update(status="listing_error", error="pagination loop")
                save(state)
                break
            state["pending"].append(following)
        save(state)
    save(state)
    return state


def run_fetch(
    configs=None,
    *,
    entries=None,
    limit=None,
    max_minutes=None,
    retry_failed=False,
    refresh=False,
    workers=1,
    commune_max_minutes=None,
    emit=print,
):
    """Resumable archive job; limit is new download attempts per commune per run."""
    if not 1 <= workers <= 8:
        raise ValueError("workers must be between 1 and 8")
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    if max_minutes is not None and max_minutes <= 0:
        raise ValueError("max_minutes must be positive")
    if commune_max_minutes is not None and commune_max_minutes <= 0:
        raise ValueError("commune_max_minutes must be positive")
    configs = (
        load_sources()
        if configs is None
        else [ArchiveSourceConfig.model_validate(c) for c in configs]
    )
    entries = load_register() if entries is None else entries
    configs = validate_sources(configs, entries)
    register = {e.bfs_id: e for e in entries}

    # A bounded second pass should reach untouched communes before deepening the first ones.
    def priority(source):
        # Retain only the sort key, not every commune's full document inventory.
        return scheduling.source_priority(read(source.bfs_id), refresh=refresh)

    configs.sort(key=priority)
    settings.ensure_dirs()
    deadline = time.monotonic() + max_minutes * 60 if max_minutes is not None else None
    with locked(), http.make_client() as client:
        polite = http.Politeness(client, max(2.0, settings.request_delay_seconds), settings.ua)
        index = store.load_index()

        def work(config):
            storage.require_space(store.MAX_PDF_BYTES)
            if deadline is not None and time.monotonic() >= deadline:
                return None
            state = fetch_one(
                config,
                register.get(config.bfs_id),
                client,
                polite,
                index,
                limit=limit,
                deadline=scheduling.commune_deadline(deadline, commune_max_minutes),
                retry_failed=retry_failed,
                refresh=refresh,
            )
            return json.dumps(summary(state), ensure_ascii=False)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            for result in pool.map(work, configs):
                if result is not None:
                    emit(result)
