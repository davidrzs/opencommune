"""Fingerprint commune websites and test known listing patterns. Read-only, polite, no PDFs downloaded.

Usage: uv run python scripts/probe_vendors.py communes_all.json out.json [--limit N] [--min-pop P]
Input rows: {bfs, name, canton, website, pop}. Output: per commune the detected vendor, the pattern that
works (if any), sample documents, and a ready-to-paste communes.yaml block.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from opencommune.config import settings
from opencommune.crawl.adapters.html_links import HtmlLinksAdapter
from opencommune.crawl.http import Politeness
from opencommune.schemas import AdapterStep

VENDOR_MARKERS = [
    ("i-web", re.compile(r"icms-|/_rte/|/_rtr/|i-web\.ch|icmsTable", re.IGNORECASE)),
    ("govis", re.compile(r"dms-folderlink|GOViS|backslash\.ch|opendcategory", re.IGNORECASE)),
    ("onegov", re.compile(r"onegov", re.IGNORECASE)),
    ("cmi", re.compile(r"cmiaxioma|cmi\.ch|cmiag", re.IGNORECASE)),
    ("nexplore", re.compile(r"nexplore", re.IGNORECASE)),
    ("localcities", re.compile(r"localcities", re.IGNORECASE)),
    ("typo3", re.compile(r"typo3", re.IGNORECASE)),
    ("wordpress", re.compile(r"wp-content", re.IGNORECASE)),
    ("drupal", re.compile(r"drupal", re.IGNORECASE)),
    ("umbraco", re.compile(r"umbraco", re.IGNORECASE)),
]
PROTOKOLL_LINK = re.compile(
    r"protokoll|proc[eè]s[- _]verba|verbali|verbale|beschl|(?<![a-z])pv(?![a-z])|risoluzion|d[ée]lib[ée]r|d[ée]cisions",
    re.IGNORECASE,
)
SESSION_WORDS = re.compile(
    r"gemeindeversammlung|einwohnerrat|gemeindeparlament|grosser gemeinderat|parlament|stadtrat|conseil communal|conseil général|conseil de ville|consiglio comunale|assemblea|sitzung|s[ée]ance|seduta",
    re.IGNORECASE,
)
SITEMAP_WORDS = re.compile(
    r"protokoll|proc[eè]s[- _]?verba|verbali|verbale|beschl|/pv[-_/]|risoluzion|d[ée]lib[ée]r",
    re.IGNORECASE,
)
# search terms for the WordPress media endpoint, tried in this order until one answers with dated files
WP_TERMS = {
    "de": ["protokoll", "beschl"],
    "fr": ["verbal", "pv", "proces"],
    "it": ["verbale", "risoluzioni"],
}
CANTON_LANG = {
    "GE": "fr", "VD": "fr", "NE": "fr", "JU": "fr", "TI": "it",
    "FR": "fr", "VS": "fr", "BE": "de", "GR": "de",
}  # fmt: skip
HOME_LINKS = 8  # candidate pages taken from the home page
SITEMAP_LINKS = 4
PAGES_PER_SITE = 10  # hard cap on content pages fetched per site
ADAPTER = HtmlLinksAdapter()
_thread = threading.local()
TODAY = dt.date.today()


def client() -> tuple[httpx.Client, Politeness]:
    if not hasattr(_thread, "client"):
        _thread.client = httpx.Client(
            headers={"User-Agent": settings.ua},
            follow_redirects=True,
            timeout=httpx.Timeout(25.0, connect=10.0),
        )
        _thread.polite = Politeness(_thread.client, 1.0, settings.ua)
    return _thread.client, _thread.polite


def get(url: str) -> tuple[str, str] | None:
    c, p = client()
    try:
        if not p.allowed(url):
            return None
        p.wait(url)
        r = c.get(url)
        ctype = r.headers.get("content-type", "")
        if r.status_code != 200 or ("html" not in ctype and "xml" not in ctype):
            return None
        return r.text, str(r.url)
    except httpx.HTTPError:
        return None


def get_json(url: str) -> tuple[object, dict[str, str]] | None:
    """Parsed JSON body and response headers, or None for anything but a 200 JSON answer."""
    c, p = client()
    try:
        if not p.allowed(url):
            return None
        p.wait(url)
        r = c.get(url)
        if r.status_code != 200 or "json" not in r.headers.get("content-type", ""):
            return None
        return r.json(), dict(r.headers)
    except (httpx.HTTPError, ValueError):
        return None


def detect_vendor(html: str) -> str:
    for name, rx in VENDOR_MARKERS:
        if rx.search(html):
            return name
    return "custom"


def probe_iweb(base: str) -> dict | None:
    for slug in ("/sitzung", "/gemeindeversammlung", "/sitzungen", "/politbusiness"):
        page = get(urljoin(base, slug))
        if not page:
            continue
        html, url = page
        if "data-entities" not in html:
            continue
        sessions = ADAPTER.extract_links(
            html, url, AdapterStep(selector="a[href*='/_rte/anlass/']"), None, "dmy"
        )
        past = sorted(
            [link for link in sessions if link.date and link.date <= TODAY],
            key=lambda link: link.date,
            reverse=True,
        )
        if not past:
            continue
        for s in past[:2]:
            sp = get(s.url)
            if not sp:
                continue
            docs = ADAPTER.extract_links(
                sp[0],
                sp[1],
                AdapterStep(selector="a[href*='/_doc']", text_regex="^Protokoll"),
                None,
                "dmy",
            )
            if docs:
                return {
                    "pattern": "iweb_sitzung",
                    "listing_url": url,
                    "sessions": len(past),
                    "newest_session": past[0].date.isoformat(),
                    "session_text": past[0].text[:60],
                    "sample_docs": [(d.text[:60], d.url) for d in docs[:2]],
                    "config": {
                        "listing_urls": [url],
                        "adapter": "html_links",
                        "adapter_config": {
                            "steps": [
                                {"selector": "a[href*='/_rte/anlass/']", "max_follow": 6},
                                {"selector": "a[href*='/_doc']", "text_regex": "^Protokoll"},
                            ],
                            "max_documents": 4,
                        },
                    },
                }
    return None


def _page_links(html: str, page_url: str) -> list[tuple[str, str, str]]:
    """(text, url, kind) of the same-host links on a page: kind "protocol" when the text or path
    mentions minutes or decisions, "session" when it names a council or assembly."""
    soup = BeautifulSoup(html, "html.parser")
    host = urlsplit(page_url).netloc
    out: list[tuple[str, str, str]] = []
    for a in soup.find_all("a", href=True):
        url = urljoin(page_url, a["href"].strip())
        if urlsplit(url).netloc != host or url.lower().endswith((".pdf", ".jpg", ".png")):
            continue
        text = " ".join(a.get_text(" ", strip=True).split()) or a.get("title", "")
        if PROTOKOLL_LINK.search(text) or PROTOKOLL_LINK.search(urlsplit(url).path):
            out.append((text, url, "protocol"))
        elif SESSION_WORDS.search(text):
            out.append((text, url, "session"))
    return out


def _sitemap_links(base: str) -> list[str]:
    """Page URLs from /sitemap.xml whose path names minutes; one request, index files not followed."""
    page = get(urljoin(base, "/sitemap.xml"))
    if not page or "<urlset" not in page[0]:
        return []
    locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", page[0])
    return [u for u in locs if SITEMAP_WORDS.search(urlsplit(u).path)][:SITEMAP_LINKS]


def _dated_pdfs(html: str, page_url: str, protocol_page: bool) -> tuple[list, int, int]:
    """Dated protocol PDFs on a page, newest first, the number of PDF links of any kind, and on a
    protocol page without dated PDFs the number of dated links of any URL shape.
    On a page that itself is named after minutes every dated PDF counts (the anchors there are
    often just "Séance du 25 juin 2026"); elsewhere the link text or file name must say so."""
    docs = ADAPTER.extract_links(
        html, page_url, AdapterStep(selector="a[href*='.pdf']"), None, "dmy"
    )
    total = len(docs)
    if not protocol_page:
        docs = [
            d
            for d in docs
            if PROTOKOLL_LINK.search(d.text + " " + d.url) or SESSION_WORDS.search(d.text)
        ]
    dated = sorted(
        [d for d in docs if d.date and d.date <= TODAY], key=lambda d: d.date, reverse=True
    )
    dated_links = 0
    if not dated and protocol_page:
        # regional systems (Ticino CMS "?i=1", i-web "/_doc/") link documents without ".pdf":
        # count dated same-host links of any URL shape so the page still surfaces as a candidate
        host = urlsplit(page_url).netloc
        anylink = ADAPTER.extract_links(
            html, page_url, AdapterStep(selector="a[href]"), None, "dmy"
        )
        dated_links = sum(
            1 for d in anylink if d.date and d.date <= TODAY and urlsplit(d.url).netloc == host
        )
    return dated, total, dated_links


def probe_generic(base: str, home_html: str, home_url: str) -> dict:
    """Follow navigation links that mention protocols or councils, one hop further from council
    pages, plus the site map; accept the first page with at least two dated protocol PDFs.
    Always returns the pages tested, so a miss is reviewable."""
    queue: list[tuple[str, str, str]] = []
    links = _page_links(home_html, home_url)
    queue += [x for x in links if x[2] == "protocol"][:HOME_LINKS]
    queue += [("sitemap", u, "protocol") for u in _sitemap_links(base)]
    queue += [x for x in links if x[2] == "session"][:HOME_LINKS]
    seen: set[str] = set()
    tested: list[dict] = []
    best: dict | None = None
    while queue and len(tested) < PAGES_PER_SITE:
        text, url, kind = queue.pop(0)
        if url in seen or url.rstrip("/") == home_url.rstrip("/"):
            continue
        seen.add(url)
        page = get(url)
        if not page:
            tested.append({"url": url, "text": text[:40], "dated": None})
            continue
        protocol_page = bool(PROTOKOLL_LINK.search(text + " " + urlsplit(url).path))
        dated, pdfs, dated_links = _dated_pdfs(page[0], page[1], protocol_page)
        tested.append(
            {
                "url": page[1],
                "text": text[:40],
                "protocol_page": protocol_page,
                "pdfs": pdfs,
                "dated": len(dated),
                "dated_links": dated_links,
            }
        )
        if len(dated) >= 2 and (best is None or len(dated) > best["sessions"]):
            best = {
                "pattern": "generic_pdf_page",
                "listing_url": page[1],
                "sessions": len(dated),
                "newest_session": dated[0].date.isoformat(),
                "session_text": dated[0].text[:60],
                "sample_docs": [(d.text[:60], d.url) for d in dated[:2]],
                "config": {
                    "listing_urls": [page[1]],
                    "adapter": "html_links",
                    "adapter_config": {
                        "steps": [
                            {
                                "selector": "a[href*='.pdf']",
                                "text_regex": "protokoll|verbal|procès|beschl|versammlung|sitzung|risoluzion|delib",
                            }
                        ],
                        "max_documents": 4,
                    },
                },
            }
            if len(dated) >= 5:
                break
        elif kind == "session":
            # one hop further: the council page often links the protocol page
            queue = [x for x in _page_links(page[0], page[1]) if x[2] == "protocol"][:3] + queue
    out = best or {}
    out["pages_tested"] = tested
    return out


SPLASH_WORDS = re.compile(
    r"vai al sito|entra|zur (website|webseite|gemeinde)|weiter|acc[ée]der|entrer|enter", re.I
)


def _splash_target(html: str, home_url: str) -> str | None:
    """On a landing page with almost no links, the same-host link that says "enter the site"."""
    soup = BeautifulSoup(html, "html.parser")
    anchors = soup.find_all("a", href=True)
    if len(anchors) >= 10:
        return None
    host = urlsplit(home_url).netloc
    for a in anchors:
        url = urljoin(home_url, a["href"].strip())
        if urlsplit(url).netloc == host and SPLASH_WORDS.search(a.get_text(" ", strip=True)):
            return url
    return None


def probe_wp_media(base: str, canton: str) -> dict | None:
    """One query per search term against the WordPress media endpoint; a hit lists dated PDFs."""
    from opencommune.crawl.adapters.html_links import parse_date_with_url

    langs = [CANTON_LANG.get(canton, "de")]
    if canton in ("FR", "VS", "BE", "GR"):
        langs = ["de", "fr"] if canton != "GR" else ["de", "it"]
    for lang in langs:
        for term in WP_TERMS[lang]:
            url = f"{base.rstrip('/')}/wp-json/wp/v2/media?search={term}&mime_type=application/pdf&per_page=20"
            answer = get_json(url)
            if not answer:
                return None  # endpoint disabled or robots-blocked: no term will answer
            items, headers = answer
            if not isinstance(items, list):
                return None
            dated = []
            for it in items:
                title = re.sub(r"<[^>]+>", "", str((it.get("title") or {}).get("rendered", "")))
                src = str(it.get("source_url", ""))
                date = parse_date_with_url(title, src, None, "dmy")
                if date and date <= TODAY and (PROTOKOLL_LINK.search(title + " " + src)):
                    dated.append((date, title[:60], src))
            if len(dated) >= 2:
                dated.sort(reverse=True)
                return {
                    "pattern": "wp_media",
                    "listing_url": url,
                    "sessions": int(headers.get("x-wp-total", len(items))),
                    "newest_session": dated[0][0].isoformat(),
                    "session_text": dated[0][1],
                    "sample_docs": [(t, u) for _, t, u in dated[:2]],
                    "config": {
                        "listing_urls": [f"{base.rstrip('/')}/wp-json/wp/v2/media?search={term}"],
                        "adapter": "wp_media",
                        "adapter_config": {
                            "steps": [{"selector": "media", "text_regex": term}],
                            "max_documents": 4,
                        },
                    },
                }
    return None


SKIP_NETWORKS: list[str] = []


def _on_skipped_network(url: str) -> bool:
    import socket

    host = urlsplit(url).netloc.split(":")[0]
    try:
        ip = socket.gethostbyname(host)
    except OSError:
        return False
    return any(ip.startswith(n) for n in SKIP_NETWORKS)


def probe(row: dict) -> dict:
    out = {
        "bfs": row["bfs"],
        "name": row["name"],
        "canton": row["canton"],
        "pop": int(row["pop"]),
        "website": row["website"],
        "vendor": None,
        "pattern": None,
    }
    if _on_skipped_network(row["website"]):
        out["vendor"] = "skipped-network"
        return out
    home = get(row["website"])
    if not home:
        out["vendor"] = "unreachable"
        return out
    html, url = home
    splash = _splash_target(html, url)
    if splash:  # a landing page with one "enter the site" link (Ticino CMS, some custom builds)
        inner = get(splash)
        if inner:
            html, url = inner
            out["splash"] = True
    out["vendor"] = detect_vendor(html)
    out["home"] = url
    if out["vendor"] == "govis" and "/route/core-hp" in html:
        out["route_variant"] = True  # content rendered client-side from a robots-disallowed route
    found = None
    if out["vendor"] == "i-web":
        found = probe_iweb(url)
    if not found and out["vendor"] == "wordpress":
        found = probe_wp_media(url, row["canton"])
    if not found:
        found = probe_generic(url, html, url)
    if found:
        out.update(found)
    tested = out.get("pages_tested") or []
    if out.get("pattern"):
        out["outcome"] = out["pattern"]
    elif out.get("route_variant"):
        out["outcome"] = "govis_route_js"
    elif any(p.get("protocol_page") and (p.get("dated_links") or 0) >= 2 for p in tested):
        out["outcome"] = "protocol_page_dated_links"  # dated links without ".pdf": selector needed
    elif any(p.get("protocol_page") and p.get("pdfs") for p in tested):
        out["outcome"] = "protocol_page_undated"  # the page exists, dates need a rule
    elif any(p.get("protocol_page") for p in tested):
        out["outcome"] = "protocol_page_no_pdfs"  # named page without PDF links: JS or subpages
    elif not tested and len(BeautifulSoup(html, "html.parser").find_all("a", href=True)) < 10:
        out["outcome"] = "js_home"  # the home page carries no navigation without JavaScript
    elif not tested:
        out["outcome"] = "no_candidate_pages"
    else:
        out["outcome"] = "no_dated_pdfs"
    return out


def main() -> None:
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 300
    min_pop = int(sys.argv[sys.argv.index("--min-pop") + 1]) if "--min-pop" in sys.argv else 3000
    skip = (
        {int(x) for x in sys.argv[sys.argv.index("--skip") + 1].split(",")}
        if "--skip" in sys.argv
        else set()
    )
    if "--skip-network" in sys.argv:
        SKIP_NETWORKS.extend(sys.argv[sys.argv.index("--skip-network") + 1].split(","))
    rows = [r for r in json.loads(src.read_text()) if r["pop"] >= min_pop and r["bfs"] not in skip][
        :limit
    ]
    results = []
    if "--resume" in sys.argv and dst.exists():  # keep what an interrupted run wrote
        results = json.loads(dst.read_text())
        done = {r["bfs"] for r in results}
        rows = [r for r in rows if r["bfs"] not in done]
    print(f"probing {len(rows)} communes", flush=True)
    workers = int(sys.argv[sys.argv.index("--workers") + 1]) if "--workers" in sys.argv else 12
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, res in enumerate(pool.map(probe, rows), 1):
            results.append(res)
            if res.get("pattern"):
                print(
                    f"  ok  {res['name']} ({res['canton']}, {res['vendor']}): {res['pattern']}, {res['sessions']} sessions, newest {res['newest_session']}",
                    flush=True,
                )
            else:
                print(
                    f"  --  {res['name']} ({res['canton']}, {res['vendor']}): {res.get('outcome')}, "
                    f"{len(res.get('pages_tested') or [])} pages tested",
                    flush=True,
                )
            if i % 25 == 0:
                print(f"  ... {i}/{len(rows)}", flush=True)
                dst.write_text(json.dumps(results, ensure_ascii=False, indent=1))
    dst.write_text(json.dumps(results, ensure_ascii=False, indent=1))
    vendors = {}
    for r in results:
        vendors[r["vendor"]] = vendors.get(r["vendor"], 0) + 1
    hits = [r for r in results if r.get("pattern")]
    print(f"\nvendors: {dict(sorted(vendors.items(), key=lambda kv: -kv[1]))}")
    print(
        f"working patterns: {len(hits)} of {len(results)}: "
        + ", ".join(f"{r['name']} {r['canton']}" for r in hits)
    )


if __name__ == "__main__":
    main()
