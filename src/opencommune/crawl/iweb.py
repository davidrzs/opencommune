"""Resumable, sequential inventory of public i-web document listings.

Machine observations live under data/discovery, never in the human coverage register.
Only linked public URLs and a small set of listing routes are visited: no document-ID scans.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import time
from types import SimpleNamespace
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from ..config import settings
from ..schemas import AdapterStep, DocumentLink
from . import http, store
from .adapters.html_links import HtmlLinksAdapter, unpack_embedded_tables
from .checkpoints import Checkpoints

SEEDS = ("/", "/sitemap", "/sitzung", "/publikationen", "/reglemente", "/downloads")
PAGE_HINT = re.compile(
    r"sitzung|versammlung|politbusiness|polprotokoll|protokoll|beschluss|beschlüsse|"
    r"publikation|dokument|download|reglement|verordnung|finanz|budget|rechnung|archiv|"
    r"jahresbericht|gesch.ftsbericht|steuer|financ|comptes?|rapport.{0,20}gestion|fiscal|"
    r"seances?|séances?|assembl|conseil|proc.s.verba|d.cision|r.glement|publication|"
    r"sedut|consiglio|verbal|risoluzion|document|regolament|preventiv|consuntiv|"
    r"bilanc|rendicont|piano.{0,20}finanziario|/_rte/anlass/",
    re.I,
)
FILE = re.compile(r"\.(?:pdf|zip|docx?|xlsx?|pptx?|jpe?g|png|gif|mp[34])$", re.I)
DOCUMENT = re.compile(r"/_doc(?:/|$)|\.pdf(?:\?|$)", re.I)
PUBLICATION_DETAIL = re.compile(r"/_rte/publikation/\d+/?$", re.I)
PAGER = "a[rel~='next'], .pagination a[href], .pager a[href], a.page-link[href]"
ADAPTER = HtmlLinksAdapter()


CHECKPOINTS = Checkpoints("iweb", "i-web")
directory, read, save, locked = (
    CHECKPOINTS.directory,
    CHECKPOINTS.read,
    CHECKPOINTS.save,
    CHECKPOINTS.locked,
)


def clean_url(url: str) -> str | None:
    p = urlsplit(url)
    if p.scheme not in {"https", "http"} or not p.hostname or p.username or p.password:
        return None
    return store.canonical_url(urlunsplit((p.scheme, p.netloc, p.path or "/", p.query, "")))


def same_site(url: str, website: str) -> bool:
    return (urlsplit(url).hostname or "").removeprefix("www.") == (
        urlsplit(website).hostname or ""
    ).removeprefix("www.")


def page_links(html: str, base: str, website: str) -> tuple[list[dict], list[str], list[dict]]:
    """All attachments, recognised archive/session pages and explicitly non-PDF attachments.

    No title-based document filter and no date cut-off. Embedded i-web tables go through the
    existing adapter; dates are read from documents, never inherited from a generic page.
    """
    soup = BeautifulSoup(unpack_embedded_tables(html), "html.parser")
    excluded = {}
    for row in soup.select("tr"):
        kind = row.select_one(".icms-document-type-and-size")
        if kind and re.search(r"\b(?:ZIP|DOCX?|XLSX?|PPTX?)\b", kind.get_text(), re.I):
            for a in row.select("a[href]"):
                url = clean_url(urljoin(base, a["href"]))
                if url and DOCUMENT.search(url):
                    excluded[url] = {"url": url, "reason": kind.get_text(" ", strip=True)}
            row.decompose()
    documents = []
    for link in ADAPTER.extract_links(
        str(soup), base, AdapterStep(selector="a[href]", context="row"), None, "dmy"
    ):
        url = clean_url(link.url)
        if url and DOCUMENT.search(url) and url not in excluded:
            documents.append(
                {
                    "url": url,
                    "title": link.text,
                    "date": str(link.date) if link.date else None,
                    "date_precision": link.date_precision,
                    "listing_url": base,
                }
            )
    pages = {}
    pagers = {id(a) for a in soup.select(PAGER)}
    for a in soup.select("a[href], link[rel~='next'][href]"):
        url = clean_url(urljoin(base, a["href"]))
        if not url or not same_site(url, website) or DOCUMENT.search(url):
            continue
        p = urlsplit(url)
        if FILE.search(p.path) or re.search(r"login|logout|signout|/suche|/search", p.path, re.I):
            continue
        if (
            PAGE_HINT.search(a.get_text(" ", strip=True) + " " + p.path)
            or id(a) in pagers
            or a.name == "link"
        ):
            pages[url] = None
    return documents, list(pages), list(excluded.values())


def initial(entry) -> dict:
    seeds = [urljoin(entry.website, path) for path in SEEDS[:2]]
    seeds += [
        p.listing_url
        for p in entry.publications
        if p.listing_url and same_site(p.listing_url, entry.website)
    ]
    seeds += [urljoin(entry.website, path) for path in SEEDS[2:]]
    seeds = list(dict.fromkeys(u for s in seeds if (u := clean_url(s))))
    return {
        "version": 1,
        "bfs_id": entry.bfs_id,
        "name": entry.name,
        "canton": entry.canton,
        "website": entry.website,
        "seeds": seeds,
        "optional_routes": [urljoin(entry.website, path) for path in SEEDS[1:]],
        "pending": seeds.copy(),
        "pages": {},
        "documents": {},
        "excluded": {},
        "downloads": {},
    }


class WebsiteChanged(ValueError):
    """The register names another site than the saved inventory; a person must review it."""


def discover_one(
    entry,
    client,
    polite,
    *,
    page_budget: int = 100,
    retry_failed: bool = False,
    refresh: bool = False,
    deadline: float | None = None,
) -> dict:
    state = read(entry.bfs_id) or initial(entry)
    if state["website"] != entry.website:
        # The same host under another scheme or with/without www is the same inventory.
        if not same_site(state["website"], entry.website):
            raise WebsiteChanged(
                f"{entry.bfs_id}: website changed; move its old inventory before rescanning"
            )
        state["website"] = entry.website
    if refresh:
        state["pending"], state["pages"], state["resolved"] = state["seeds"].copy(), {}, {}
        state["refreshed_at"] = dt.datetime.now(dt.UTC).isoformat()
    state.setdefault(
        "resolved", {p["resolved_url"]: u for u, p in state["pages"].items() if p["status"] == "ok"}
    )
    if retry_failed:
        for url, page in state["pages"].items():
            if page["status"] == "failed" and url not in state["pending"]:
                state["pending"].append(url)
    for _ in range(page_budget):
        if not state["pending"] or (deadline is not None and time.monotonic() >= deadline):
            break
        # Publication detail pages usually expose the attachment directly. Avoid spending a
        # short pass on hundreds of event pages before reaching already-linked publications.
        # Stable sorting also upgrades saved queues without dropping or inventing any URLs.
        state["pending"].sort(
            key=lambda u: not bool(PUBLICATION_DETAIL.fullmatch(urlsplit(u).path))
        )
        url = state["pending"][0]  # leave queued until the page and its discoveries are persisted
        if url in state["resolved"]:
            state["pending"].pop(0)
            save(state)
            continue
        try:
            if not polite.allowed(url):
                raise http.FetchFailure("robots", url, "disallowed by robots.txt")
            response = http._send(client, polite, client.build_request("GET", url))
            try:
                http._ensure_ok(response, url)
                final_url = str(response.url)
                if not same_site(final_url, entry.website):
                    raise http.FetchFailure("redirect", url, "listing redirects to another site")
                if "html" not in response.headers.get("content-type", "text/html"):
                    raise http.FetchFailure("content_type", url, "listing is not HTML")
                documents, pages, excluded = page_links(response.text, final_url, entry.website)
            finally:
                response.close()
        except http.FetchFailure as exc:
            # Missing speculative routes are normal; a missing linked page is an incomplete crawl.
            status = (
                "absent"
                if exc.status in {404, 410} and url in state["optional_routes"]
                else "failed"
            )
            state["pages"][url] = {"status": status, "kind": exc.kind, "message": exc.message}
        except (ValueError, TypeError, KeyError) as exc:
            state["pages"][url] = {"status": "failed", "kind": "parse", "message": str(exc)}
        else:
            state["resolved"][final_url] = url
            state["pages"][url] = {
                "status": "ok",
                "resolved_url": final_url,
                "documents": len(documents),
            }
            for document in documents:
                held = state["documents"].setdefault(document["url"], {**document, "listings": []})
                if final_url not in held["listings"]:
                    held["listings"].append(final_url)
            state["excluded"].update({e["url"]: e for e in excluded})
            for page in pages:
                if (
                    page not in state["pages"]
                    and page not in state["pending"]
                    and page not in state["resolved"]
                ):
                    state["pending"].append(page)
        state["pending"].pop(0)
        save(state)
        if state["pages"][url].get("kind") == "robots":
            break  # do not spend the run probing other routes on a disallowed host
    return state


def download_one(
    state,
    commune,
    client,
    polite,
    index,
    *,
    limit: int | None = None,
    retry_failed: bool = False,
    deadline: float | None = None,
):
    """Use the production SHA/URL store without rewalking any listing pages.

    Mixed archive downloads use an unknown body; an inventory never guesses it.
    Its JSON retains every listing occurrence, including duplicate-content URLs.
    """
    attempted = 0
    for url, doc in state["documents"].items():
        if deadline is not None and time.monotonic() >= deadline:
            break
        previous = state["downloads"].get(url, {})
        known = index.get(store.canonical_url(url))
        if known and store.held(known["sha256"]):
            state["downloads"][url] = {"status": "held", "sha256": known["sha256"]}
            continue
        if previous.get("status") in {"not_pdf", "failed"} and not retry_failed:
            continue
        if not same_site(doc["listing_url"], state["website"]) or not same_site(
            url, state["website"]
        ):
            state.setdefault("review_documents", {})[url] = "external_document_or_listing"
            continue
        if limit is not None and attempted >= limit:
            break
        attempted += 1
        # Archive scope is mixed: dates and legislative type are not inferred from the listing.
        link = DocumentLink(**{k: v for k, v in doc.items() if k != "listings"}, body=commune.body)
        try:
            store._download(link, commune, client, polite, index)
        except http.FetchFailure as exc:
            state["downloads"][url] = {
                "status": "not_pdf" if exc.kind == "not_pdf" else "failed",
                "kind": exc.kind,
                "message": exc.message,
            }
        else:
            state["downloads"][url] = {
                "status": "held",
                "sha256": index[store.canonical_url(url)]["sha256"],
            }
        save(state)
        if state["downloads"][url].get("kind") == "robots":
            break
    save(state)
    return state


def summary(state: dict) -> dict:
    statuses = [p["status"] for p in state["pages"].values()]
    downloads = [d["status"] for d in state["downloads"].values()]
    return {
        "bfs_id": state["bfs_id"],
        "name": state["name"],
        "pages": len(statuses),
        "pending_pages": len(state["pending"]),
        "failed_pages": statuses.count("failed"),
        "document_candidates": len(state["documents"]),
        "held_urls": downloads.count("held"),
        "onboarding": state.get("onboarding"),
        "review_documents": len(state.get("review_documents", {})),
        "non_pdf": downloads.count("not_pdf") + len(state["excluded"]),
        "failed_downloads": downloads.count("failed"),
        "listing_queue_exhausted": not state["pending"] and "failed" not in statuses,
    }


def archive_source(entry, state):
    """Validate automatic archive attribution without inventing a body or language."""
    from ..communes import bfs_register

    reason = None
    identity = bfs_register().get(entry.bfs_id)
    if identity is None or identity[1] != entry.canton:
        reason = "registry_identity_mismatch"
    elif entry.vendor != "i-web" or state.get("website") != entry.website:
        reason = "website_or_vendor_changed"
    elif not state["documents"]:
        reason = "no_document_candidates"
    state["onboarding"] = {"status": "review" if reason else "eligible", "reason": reason}
    save(state)
    if reason:
        return None
    return SimpleNamespace(
        bfs_id=entry.bfs_id, name=entry.name, canton=entry.canton, body="unknown"
    )


def run(
    entries,
    *,
    mode: str,
    communes=(),
    page_budget=100,
    limit=None,
    retry_failed=False,
    refresh=False,
    max_minutes=None,
    emit=print,
):
    settings.ensure_dirs()
    # Repeated bounded syncs advance across the register before deepening existing inventories.
    if mode == "sync":
        entries = sorted(
            entries,
            key=lambda e: (
                (read(e.bfs_id) or {}).get("refreshed_at", "") if refresh else "",
                len((read(e.bfs_id) or {}).get("pages", {})),
            ),
        )
    deadline = time.monotonic() + max_minutes * 60 if max_minutes is not None else None
    with locked(), http.make_client() as client:
        # One worker and one shared limiter, even when different domains resolve to one hoster.
        delay = max(2.0, settings.request_delay_seconds)
        polite = http.Politeness(client, delay, settings.ua)
        for entry in entries:
            polite._network(urlsplit(entry.website).netloc)
        index = store.load_index() if mode in {"fetch", "sync"} else {}
        for entry in entries:
            if deadline is not None and time.monotonic() >= deadline:
                emit(
                    json.dumps(
                        {"status": "time_budget_reached", "resume": "repeat the same command"}
                    )
                )
                break
            if mode in {"discover", "sync"}:
                try:
                    state = discover_one(
                        entry,
                        client,
                        polite,
                        page_budget=page_budget,
                        retry_failed=retry_failed,
                        refresh=refresh,
                        deadline=deadline,
                    )
                except WebsiteChanged:
                    # One commune awaiting review must not stop the pass for all the others.
                    emit(json.dumps({"bfs_id": entry.bfs_id, "status": "website_changed"}))
                    continue
            else:
                state = read(entry.bfs_id)
            if mode in {"fetch", "sync"}:
                if state is None:
                    emit(json.dumps({"bfs_id": entry.bfs_id, "status": "needs_inventory"}))
                    continue
                commune = archive_source(entry, state)
                if commune is None:
                    emit(json.dumps(summary(state), ensure_ascii=False))
                    continue
                state = download_one(
                    state,
                    commune,
                    client,
                    polite,
                    index,
                    limit=limit,
                    retry_failed=retry_failed,
                    deadline=deadline,
                )
            emit(json.dumps(summary(state), ensure_ascii=False))
