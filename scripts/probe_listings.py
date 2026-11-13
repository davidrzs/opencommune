"""Look for public PDF listings on the registered sites of one vendor (TYPO3, Drupal, GOViS, custom or
unknown).

Run: uv run python scripts/probe_listings.py [--vendor typo3|drupal|govis|custom|unknown] [--commune BFS,...]
Resumable; results go to data/discovery/<vendor>/probe.json and pages/ (outside git).
Only linked pages and standard sitemap.xml are visited; no file IDs are guessed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import logging
import re
import threading
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree

import httpx
from bs4 import BeautifulSoup
from probe_wordpress import DeferredNetwork, ScopedPoliteness

from opencommune.config import settings
from opencommune.crawl import fetch, http
from opencommune.crawl.adapters.html_links import _base_href, is_pdf_candidate, unwrap_viewer
from opencommune.crawl.iweb import clean_url, same_site
from opencommune.crawl.linked_archive import LinkedSource
from opencommune.crawl.linked_archive import documents as archive_documents
from opencommune.crawl.sites.nextjs import link_tags as nextjs_links
from opencommune.register import load_register

WORDS = re.compile(
    r"protokoll|proc[eè]s|verb(?:al|aux)|beschl|gemeindeversammlung|urversammlung|"
    r"parlament|einwohnerrat|conseil|consiglio|assemble|sitzung|s[ée]ance|sedut|"
    r"publika|pubblica|publication|dokument|document|download|reglement|r[eè]glement|"
    r"budget|rechnung|comptes|finanz|financ|rapport|bericht|botschaft|abstimm|votat|"
    r"politik|politique|politica|verwaltung|administration|autorite|autorit[eé]|beh[oö]rd|"
    r"anschlagsbrett|mitteilung|actualit|aktuelles|willkommen|bienvenue|benvenut|"
    r"online.?schalter|guichet|regolament|ordinanz|risoluzion|messagg|preventiv|consuntiv|modul|albo|"
    r"(?:gemeinde|commune|comune)(?:/|$)",
    re.I,
)
PRIORITY = re.compile(
    r"protokoll|proc[eè]s|verb(?:al|aux)|document|dokument|download|versammlung|assemble|budget|rechnung|"
    r"reglement|r[eè]glement|online.?schalter|guichet|regolament|ordinanz|risoluzion|"
    r"messagg|preventiv|consuntiv|modul|albo",
    re.I,
)
ASSET = re.compile(r"\.(?:jpg|jpeg|png|gif|svg|webp|zip|docx?|xlsx?|ics|mp4|mp3|css|js)$", re.I)
ARCHIVE_PRIORITY = re.compile(
    r"protokoll|proc[eè]s|verb(?:al|aux)|versammlung|reglement|r[eè]glement|regolament|"
    r"budget|rechnung|compt|consuntiv|preventiv|dokument|document|download",
    re.I,
)
PDF_PREFIX_BYTES = 1024


def platform_hints(html, base=None):
    """Record technical clues, not automatic vendor relabelling."""
    soup = BeautifulSoup(html, "html.parser")
    hints = {
        "generator:" + str(m.get("content", ""))[:120]
        for m in soup.select('meta[name="generator" i]')
        if m.get("content")
    }
    local_urls = []
    for node in soup.select("[href], [src]"):
        raw = str(node.get("href") or node.get("src") or "")
        try:
            if base is None or same_site(urljoin(base, raw), base):
                local_urls.append(raw)
        except ValueError:
            continue
    urls = " ".join(local_urls).lower()
    for label, marker in {
        "wordpress": "/wp-content/",
        "typo3": "/fileadmin/",
        "drupal": "/sites/default/files/",
        "govis": "/public/upload/assets/",
        "assolo": "assolo",
        "aajax-assets": "/aajax/",
        "weblication": "/weblication/",
        "onegov": "onegov",
        "joomla": "/media/system/js/",
        "contao": "/bundles/contao",
        "i-web": "/_rte/",
        "nextjs": "/_next/",
        "quicksite": "/qsportal/",
        "wix": "wixstatic.com",
        "magnolia": "/.resources/",
    }.items():
        if marker in urls:
            hints.add(label)
    return sorted(hints)


def links(html, base, website):
    docs, pages = {}, {}
    soup = BeautifulSoup(html, "html.parser")
    resolution_base = _base_href(soup, base)
    for a in [*soup.select("a[href]"), *nextjs_links(soup)]:
        try:
            url = clean_url(unwrap_viewer(urljoin(resolution_base, a["href"].strip())))
        except ValueError:
            continue
        if not url:
            continue
        text = " ".join(a.get_text(" ", strip=True).split())[:200]
        path = urlsplit(url).path
        if is_pdf_candidate(a, url):
            docs[url] = {
                "url": url,
                "text": text,
                "listing_url": base,
                "same_site": same_site(url, website),
            }
        elif same_site(url, website) and not ASSET.search(path) and WORDS.search(text + " " + path):
            pages[url] = 0 if PRIORITY.search(text + " " + path) else 1
    # Reuse the production readers for iframe/viewer/widget/hydration files.
    # External hosts still need an independently reviewed attribution scope.
    source = LinkedSource(bfs_id=1, website=website, vendor="custom", listing_urls=[website])
    for url in archive_documents(html, base, source):
        docs.setdefault(url, {"url": url, "text": "", "listing_url": base, "same_site": True})
    return list(docs.values()), sorted(pages, key=lambda u: pages[u])


def sitemap_links(body, website):
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError:
        return [], []
    locs = [n.text.strip() for n in root.iter() if n.tag.rsplit("}", 1)[-1] == "loc" and n.text]
    locs = [u for u in locs if clean_url(u) and same_site(u, website)]
    if root.tag.rsplit("}", 1)[-1] == "sitemapindex":
        return locs[:2], []
    return [], [u for u in locs if WORDS.search(urlsplit(u).path)]


def request(url, client, polite, *, prefix=False):
    if not polite.allowed(url):
        return {"url": url, "status": "robots"}, b""
    headers = (
        {"Range": f"bytes=0-{PDF_PREFIX_BYTES - 1}", "Accept-Encoding": "identity"}
        if prefix
        else None
    )
    response = http._send(
        client, polite, client.build_request("GET", url, headers=headers), stream=True
    )
    try:
        meta = {"url": str(response.url), "http_status": response.status_code}
        if response.status_code != 200 and not (prefix and response.status_code == 206):
            return dict(
                meta, status="http_error", retry_after=response.headers.get("retry-after")
            ), b""
        ctype = response.headers.get("content-type", "").lower()
        if prefix:
            # Range can be ignored. Still read at most one bounded raw chunk
            # and close the response; never decompress an entire encoded file.
            if response.headers.get("content-encoding", "identity").lower() != "identity":
                return dict(meta, status="unsupported_encoding", content_type=ctype), b""
            body = next(response.iter_raw(chunk_size=PDF_PREFIX_BYTES), b"")
            return dict(meta, status="ok", content_type=ctype), body[:PDF_PREFIX_BYTES]
        if not prefix and "application/pdf" in ctype:
            first = next(response.iter_bytes(chunk_size=1024), b"")
            return dict(
                meta,
                status="pdf_document",
                content_type=ctype,
                pdf_signature=first.lstrip().startswith(b"%PDF-"),
            ), b""
        if not prefix and not any(t in ctype for t in ("html", "xml", "text/plain")):
            return dict(meta, status="unsupported_type", content_type=ctype), b""
        body = bytearray()
        for chunk in response.iter_bytes(chunk_size=65536):
            body.extend(chunk)
            if len(body) > 2_000_000:
                break
        if not prefix and len(body) > 2_000_000:
            return dict(meta, status="too_large"), b""
        return dict(meta, status="ok", content_type=ctype), bytes(body)
    finally:
        response.close()


def safe_request(url, client, polite, **kwargs):
    try:
        return request(url, client, polite, **kwargs)
    except DeferredNetwork as exc:
        return {"url": url, "status": "deferred_network", "reason": str(exc)}, b""
    except (http.FetchFailure, httpx.HTTPError, ValueError) as exc:
        return {"url": url, "status": "network_error", "reason": str(exc)}, b""


def probe(entry, client, polite, directory, page_budget):
    row = {
        "bfs_id": entry.bfs_id,
        "name": entry.name,
        "canton": entry.canton,
        "website": entry.website,
        "original_status": entry.status,
        "checked_at": dt.datetime.now(dt.UTC).isoformat(),
        "pages": [],
        "documents": [],
        "pdf_checks": [],
        "platform_hints": [],
    }
    if not entry.website:
        return dict(row, status="missing_website")
    polite.website = entry.website
    seeds = [
        fetch._expand_ranges([p.listing_url])[0]
        for p in entry.publications
        if p.listing_url and same_site(p.listing_url, entry.website)
    ]
    # Review the homepage even for configured sites, then existing sources and broader navigation.
    queue = list(dict.fromkeys([entry.website, *seeds, urljoin(entry.website, "/sitemap.xml")]))
    seen, docs = set(), {}
    while queue and len(row["pages"]) < page_budget:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        meta, body = safe_request(url, client, polite)
        row["pages"].append(meta)
        if meta.get("http_status") == 429:
            break  # no further requests to a throttled commune in this run
        if meta["status"] == "pdf_document" and meta["pdf_signature"]:
            url = meta["url"]
            docs[url] = {
                "url": url,
                "text": "",
                "listing_url": url,
                "same_site": same_site(url, entry.website),
            }
            row["pdf_checks"].append(meta)
            continue
        if meta["status"] != "ok":
            continue
        final = meta["url"]
        seen.add(final)
        name = f"{entry.bfs_id}-{hashlib.sha256(final.encode()).hexdigest()[:16]}.html"
        (directory / "pages" / name).write_bytes(body)
        meta["snapshot"] = "pages/" + name
        if re.search(rb"<(?:\w+:)?(?:urlset|sitemapindex)(?:\s|>)", body[:4096]):
            indexes, found = sitemap_links(body, entry.website)
            queue.extend(u for u in indexes + found if u not in seen and u not in queue)
            continue
        row["platform_hints"] = sorted(
            set(row["platform_hints"])
            | set(platform_hints(body.decode("utf-8", errors="replace"), final))
        )
        found_docs, found_pages = links(
            body.decode("utf-8", errors="replace"), final, entry.website
        )
        for doc in found_docs:
            docs.setdefault(doc["url"], doc)
        meta["pdf_links"] = len(found_docs)
        queue.extend(u for u in found_pages if u not in seen and u not in queue)
        # Follow specific document pages before broad homepage/news navigation fills the budget.
        queue.sort(
            key=lambda u: (
                0
                if ARCHIVE_PRIORITY.search(urlsplit(u).path)
                else 1
                if PRIORITY.search(urlsplit(u).path)
                else 2
            )
        )
    row["documents"] = list(docs.values())
    row["pending_pages"] = len([u for u in queue if u not in seen])
    # Confirm file signatures, not just '.pdf' links. External file hosts remain for review.
    throttled = any(p.get("http_status") == 429 for p in row["pages"])
    if not throttled and not any(p["pdf_signature"] for p in row["pdf_checks"]):
        for doc in [d for d in docs.values() if d["same_site"]][:3]:
            meta, body = safe_request(doc["url"], client, polite, prefix=True)
            meta["pdf_signature"] = body.lstrip().startswith(b"%PDF-")
            row["pdf_checks"].append(meta)
            if meta["pdf_signature"] or meta.get("http_status") == 429:
                break
    row["status"] = (
        "verified_pdf"
        if any(p["pdf_signature"] for p in row["pdf_checks"])
        else "pdf_links_unverified"
        if docs
        else "no_pdf_found"
        if any(p["status"] == "ok" for p in row["pages"])
        else "unreachable_or_blocked"
    )
    return row


def eligible(entry, results, retry_incomplete):
    previous = results.get(str(entry.bfs_id))
    if previous is None:
        return True
    if not retry_incomplete or previous["status"] == "verified_pdf":
        return False
    # Leave throttled sites for a later, manually scheduled review; never retry in this sweep.
    return not any(p.get("http_status") == 429 for p in previous["pages"] + previous["pdf_checks"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--vendor", choices=("typo3", "drupal", "govis", "custom", "unknown"), default="typo3"
    )
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--commune")
    selection.add_argument("--commune-file", type=Path, help="JSON list of selected BFS IDs")
    parser.add_argument("--workers", type=int, choices=range(1, 5), default=4)
    parser.add_argument(
        "--output", type=Path, help="Separate evidence directory for a fresh depth review"
    )
    parser.add_argument("--page-budget", type=int, choices=range(3, 21), default=8)
    parser.add_argument(
        "--retry-incomplete",
        action="store_true",
        help="Recheck misses and errors, preserving verified and throttled sites",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    entries = [e for e in load_register() if (e.vendor or "unknown") == args.vendor]
    if args.commune or args.commune_file:
        ids = (
            json.loads(args.commune_file.read_text())
            if args.commune_file
            else [int(x) for x in args.commune.split(",")]
        )
        if not isinstance(ids, list) or any(type(x) is not int for x in ids):
            parser.error("commune file must contain a JSON list of integer BFS IDs")
        wanted = set(ids)
        if wanted - {e.bfs_id for e in entries}:
            parser.error("selected BFS IDs must belong to the requested vendor")
        entries = [e for e in entries if e.bfs_id in wanted]
    if args.vendor == "custom":
        entries.sort(key=lambda e: (e.status != "candidate", e.bfs_id))
    directory = args.output or settings.data_dir / "discovery" / args.vendor
    (directory / "pages").mkdir(parents=True, exist_ok=True)
    path = directory / "probe.json"
    results = json.loads(path.read_text()) if path.exists() else {}
    groups = defaultdict(list)
    with http.make_client() as client:
        resolver = http.Politeness(client, 2.0, settings.ua)
        for entry in entries:
            if eligible(entry, results, args.retry_incomplete):
                groups[
                    resolver._network(urlsplit(entry.website).netloc) if entry.website else None
                ].append(entry)
        networks = resolver._networks.copy()
    lock = threading.Lock()
    http.ATTEMPTS = 1

    def run_group(item):
        network, group = item
        with http.make_client() as client:
            client.timeout = httpx.Timeout(15.0, connect=8.0)
            polite = ScopedPoliteness(client, network, networks)
            for entry in group:
                result = probe(entry, client, polite, directory, args.page_budget)
                with lock:
                    results[str(entry.bfs_id)] = result
                    part = path.with_suffix(".tmp")
                    part.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n")
                    part.replace(path)
                    print(
                        json.dumps(
                            {k: result[k] for k in ("bfs_id", "name", "original_status", "status")}
                        ),
                        flush=True,
                    )

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(run_group, groups.items()))
    print(
        json.dumps(
            {
                "vendor": args.vendor,
                "selected": len(entries),
                "recorded": len(results),
                "statuses": dict(Counter(r["status"] for r in results.values())),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
