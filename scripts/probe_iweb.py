"""Discovery probe for i-web sites: which of them publish minutes or decision lists, and where.
Read-only, polite (one request per second across the shared hosting network), no PDFs downloaded.
Usage: uv run python scripts/probe_iweb.py communes.json out.json [--limit N] [--workers N]
Input rows: {bfs, name, canton, website, pop}. Output: per commune the session module found
(`/sitzung` with its past-sessions table), the document kinds attached to the newest sessions,
pages from the site map that carry protocol documents, and a ready-to-paste communes.yaml block.

Every i-web site has the same two places for council documents: the session module (`/sitzung`,
one page per session under `/sitzung/<id>` with `/_doc/<id>` attachments) and ordinary content
pages listed on `/sitemap`. The attachment names differ per commune ("Protokoll Einwohnergemeinde-
versammlung 20. November 2025", "Gemeindeversammlungsbeschlüsse", "Beschlussfassung ..."), so the
probe classifies every attachment instead of expecting one title.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from probe_vendors import get

from opencommune.crawl.adapters.html_links import HtmlLinksAdapter, parse_date
from opencommune.schemas import AdapterStep

ADAPTER = HtmlLinksAdapter()
TODAY = dt.date.today()
SESSION_SLUGS = (
    "/sitzung",
    "/sitzungen",
    "/gemeindeversammlung",
    "/politbusiness",
    "/seances",
    "/seance",
    "/assemblees",
    "/sedute",
)
SESSION_PAGE = re.compile(r"s[ée]ance|sedut|sitzung|versammlung|assembl[ée]e", re.I)
COUNCIL_HOME = re.compile(
    r"^(gemeindeversammlung(en)?|einwohnerrat|assembl[ée]e (communale|g[ée]n[ée]rale)|"
    r"conseil (g[ée]n[ée]ral|communal)|consiglio comunale)$",
    re.I,
)
MINUTES = re.compile(
    r"protokoll|proc[eè]s[- _]?verba|(?<![a-z])pv(?![a-z])|verbale|verbali", re.IGNORECASE
)
NOT_MINUTES = re.compile(
    r"auszug|genehmigung|stellungnahme|^PA |traktand|entwurf|abnahme", re.IGNORECASE
)
DECISIONS = re.compile(
    r"beschl[uü]ss|beschlussfassung|beschlüsse|d[ée]cision|d[ée]lib[ée]r|risoluzion", re.IGNORECASE
)
PAGE_WORDS = re.compile(
    r"protokoll|beschl[uü]ss|versammlung|einwohnerrat|gemeinderat|parlament|stadtrat|archiv"
    r"|proc[eè]s|verba|s[ée]ance|conseil|assembl|d[ée]cision|consiglio|verbal",
    re.IGNORECASE,
)
PAGE_HINT = re.compile(r"archiv|protokoll|beschl|proc[eè]s|verba|s[ée]ance|d[ée]cision", re.I)
BODY_WORDS = [
    (
        "parliament",
        re.compile(r"einwohnerrat|gemeindeparlament|stadtrat|grosser gemeinderat", re.I),
    ),
    ("assembly", re.compile(r"versammlung", re.I)),
    ("executive", re.compile(r"gemeinderat", re.I)),
]
SESSIONS_TO_READ = 3
PAGES_TO_READ = 3


def _doc_links(html: str, base_url: str) -> list[tuple[str, str]]:
    """(text, url) for every document attachment, read through the adapter so that links inside
    the JSON tables (`data-entities`) count too; generic "Download" anchors are dropped."""
    links = ADAPTER.extract_links(
        html, base_url, AdapterStep(selector="a[href*='/_doc'], a[href*='.pdf']"), None, "dmy"
    )
    seen: dict[str, str] = {}
    for link in links:
        text = " ".join(link.text.split())
        if text.lower() in {"download", "herunterladen", "télécharger", "pdf", ""}:
            seen.setdefault(link.url, text)
        else:
            seen[link.url] = text
    return [(t, u) for u, t in seen.items() if t]


def _classify(docs: list[tuple[str, str]]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {"minutes": [], "decisions": []}
    for text, url in docs:
        kind = None
        if MINUTES.search(text) and not NOT_MINUTES.search(text):
            kind = "minutes"
        elif DECISIONS.search(text) and not NOT_MINUTES.search(text):
            kind = "decisions"
        if kind:
            date = parse_date(text)
            out[kind].append(
                {"text": text[:80], "url": url, "date": date.isoformat() if date else None}
            )
    return out


def _body(texts: list[str]) -> str | None:
    joined = " ".join(texts)
    for body, rx in BODY_WORDS:
        if rx.search(joined):
            return body
    return None


def probe_sessions(base: str, extra_urls: list[str]) -> dict | None:
    """The session module under its usual slugs, else under a page the navigation names."""
    for url in [urljoin(base, s) for s in SESSION_SLUGS] + extra_urls:
        page = get(url)
        if not page or "data-entities" not in page[0]:
            continue
        html, url = page
        sessions = ADAPTER.extract_links(
            html, url, AdapterStep(selector="a[href*='/_rte/anlass/']"), None, "dmy"
        )
        if not sessions:  # a table of something else (publications, news)
            continue
        past = sorted(
            [s for s in sessions if s.date and s.date <= TODAY], key=lambda s: s.date, reverse=True
        )
        out = {
            "sessions_url": url,
            "sessions": len(past),
            "sessions_from": past[-1].date.isoformat() if past else None,
            "sessions_to": past[0].date.isoformat() if past else None,
            "session_titles": sorted(
                {re.sub(r"\s*\d{2}\.\d{2}\.\d{4}.*$", "", s.text).strip()[:50] for s in past}
            )[:6],
            "body": _body([s.text for s in past]),
            "session_docs": {"minutes": [], "decisions": []},
            "session_pages_read": 0,
        }
        for s in past[:SESSIONS_TO_READ]:
            sp = get(s.url)
            if not sp:
                continue
            out["session_pages_read"] += 1
            found = _classify(_doc_links(sp[0], sp[1]))
            for kind in found:
                for d in found[kind]:
                    d["session_date"] = s.date.isoformat()
                out["session_docs"][kind].extend(found[kind])
        return out
    return None


def _candidate_pages(html: str, page_url: str, candidates: dict[str, str]) -> None:
    """Same-host content pages named after minutes or decisions first, then council pages with an
    archive or protocol hint; the session module and internal routes are left out."""
    soup = BeautifulSoup(html, "html.parser")
    host = urlsplit(page_url).netloc
    anchors = []
    for a in soup.find_all("a", href=True):
        text = " ".join(a.get_text(" ", strip=True).split())
        url = urljoin(page_url, a["href"])
        path = urlsplit(url).path
        if urlsplit(url).netloc != host or path.startswith(("/sitzung", "/_")) or not text:
            continue
        if re.search(r"abstimmung|wahl|votation|[ée]lection", text + path, re.I):
            continue
        anchors.append((text, url, path))
    for text, url, path in anchors:
        if MINUTES.search(text + " " + path) or DECISIONS.search(text + " " + path):
            candidates.setdefault(url, text)
    for text, url, path in anchors:
        if PAGE_WORDS.search(text) and PAGE_HINT.search(text + path):
            candidates.setdefault(url, text)
    for text, url, _path in anchors:
        if COUNCIL_HOME.match(text):  # the council's landing page often lists the minutes
            candidates.setdefault(url, text)


def probe_pages(candidates: dict[str, str]) -> dict | None:
    """The newest documents on the protocol pages the navigation and /sitemap name."""
    out = {
        "sitemap_candidates": [(t[:50], u) for u, t in list(candidates.items())[:8]],
        "pages": [],
    }
    for url, text in list(candidates.items())[:PAGES_TO_READ]:
        p = get(url)
        if not p:
            continue
        docs = _doc_links(p[0], p[1])
        found = _classify(docs)
        n = len(found["minutes"]) + len(found["decisions"])
        named = bool(MINUTES.search(text) or DECISIONS.search(text))
        # on a page named after the minutes the attachments often carry only a date
        dated_links = sum(1 for t, _ in docs if parse_date(t)) if named and not n else 0
        if n or dated_links >= 2:
            out["pages"].append(
                {
                    "url": p[1],
                    "title": text[:50],
                    "minutes": len(found["minutes"]),
                    "minutes_dated": sum(1 for d in found["minutes"] if d["date"]),
                    "decisions": len(found["decisions"]),
                    "decisions_dated": sum(1 for d in found["decisions"] if d["date"]),
                    "dated_links": dated_links,
                    "samples": [d["text"] for d in (found["minutes"] + found["decisions"])[:3]]
                    or [t for t, _ in docs if parse_date(t)][:3],
                }
            )
    return out


def _config(res: dict) -> dict | None:
    """The block that would read the best source found, session module before content pages."""
    sd = res.get("session_docs") or {}
    if sd.get("minutes"):
        return {
            "listing_urls": [res["sessions_url"]],
            "adapter": "html_links",
            "adapter_config": {
                "steps": [
                    {"selector": "a[href*='/_rte/anlass/']", "max_follow": 8},
                    {
                        "selector": "a[href*='/_doc']",
                        "text_regex": "[Pp]rotokoll",
                        "kind": "minutes",
                    },
                ],
            },
        }
    pages = [p for p in (res.get("pages") or []) if p["minutes_dated"] >= 2]
    if pages:
        best = max(pages, key=lambda p: p["minutes_dated"])
        return {
            "listing_urls": [best["url"]],
            "adapter": "html_links",
            "adapter_config": {
                "steps": [
                    {
                        "selector": "a[href*='/_doc'], a[href*='.pdf']",
                        "text_regex": "[Pp]rotokoll",
                        "kind": "minutes",
                    }
                ],
            },
        }
    if sd.get("decisions"):
        return {
            "listing_urls": [res["sessions_url"]],
            "adapter": "html_links",
            "adapter_config": {
                "steps": [
                    {"selector": "a[href*='/_rte/anlass/']", "max_follow": 8},
                    {
                        "selector": "a[href*='/_doc']",
                        "text_regex": "[Bb]eschl",
                        "kind": "decisions",
                    },
                ],
            },
        }
    dated = [p for p in (res.get("pages") or []) if p.get("dated_links", 0) >= 2]
    if dated:
        best = max(dated, key=lambda p: p["dated_links"])
        return {  # the attachments carry only a date: the reviewer sets kind and filter
            "listing_urls": [best["url"]],
            "adapter": "html_links",
            "adapter_config": {
                "steps": [{"selector": "a[href*='/_doc'], a[href*='.pdf']", "kind": "minutes"}],
            },
        }
    return None


def _outcome(res: dict) -> str:
    sd = res.get("session_docs") or {}
    pages = res.get("pages") or []
    if sd.get("minutes"):
        return "sessions_minutes"
    if any(p["minutes_dated"] >= 2 for p in pages):
        return "page_minutes"
    if sd.get("decisions"):
        return "sessions_decisions"
    if any(p["decisions_dated"] >= 2 for p in pages):
        return "page_decisions"
    if any(p.get("dated_links", 0) >= 2 for p in pages):
        return "page_dated_links"
    if any(p["minutes"] or p["decisions"] for p in pages):
        return "page_undated"
    if res.get("sessions"):
        return "sessions_without_documents"
    if res.get("sessions_url"):
        return "sessions_empty"
    return "nothing_found"


def probe(row: dict) -> dict:
    out = {
        "bfs": row["bfs"],
        "name": row["name"],
        "canton": row["canton"],
        "pop": int(row["pop"]),
        "website": row["website"],
    }
    home = get(row["website"])
    if not home:
        out["outcome"] = "unreachable"
        return out
    base = home[1]
    out["home"] = base
    out["iweb"] = bool(re.search(r"icms-|/_rte/|/_rtr/|i-web\.ch|icmsTable", home[0], re.I))
    candidates: dict[str, str] = {}
    _candidate_pages(home[0], base, candidates)
    sitemap = get(urljoin(base, "/sitemap"))
    if sitemap:
        _candidate_pages(sitemap[0], sitemap[1], candidates)
    session_like = [u for u, t in candidates.items() if SESSION_PAGE.search(t + urlsplit(u).path)]
    sessions = probe_sessions(base, session_like[:3])
    if sessions:
        out.update(sessions)
        candidates.pop(sessions["sessions_url"], None)
    pages = probe_pages(candidates)
    if pages:
        out.update(pages)
    out["outcome"] = _outcome(out)
    config = _config(out)
    if config:
        out["config"] = config
    return out


def main() -> None:
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 10_000
    workers = int(sys.argv[sys.argv.index("--workers") + 1]) if "--workers" in sys.argv else 2
    rows = json.loads(src.read_text())[:limit]
    results: list[dict] = []
    if "--resume" in sys.argv and dst.exists():  # keep what an interrupted run wrote
        results = json.loads(dst.read_text())
        redo = set()
        if "--redo" in sys.argv:  # ... except rows with these outcomes, probed again
            redo = set(sys.argv[sys.argv.index("--redo") + 1].split(","))
            results = [r for r in results if r.get("outcome") not in redo]
        done = {r["bfs"] for r in results}
        rows = [r for r in rows if r["bfs"] not in done]
    print(f"probing {len(rows)} i-web communes with {workers} workers", flush=True)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, res in enumerate(pool.map(probe, rows), 1):
            results.append(res)
            print(
                f"  {res['outcome']:28} {res['name']} ({res['canton']}, {res['pop']}): "
                f"{res.get('sessions', 0)} sessions {res.get('sessions_from') or ''}..{res.get('sessions_to') or ''}, "
                f"session docs m={len((res.get('session_docs') or {}).get('minutes', []))} "
                f"d={len((res.get('session_docs') or {}).get('decisions', []))}, "
                f"pages={len(res.get('pages') or [])}",
                flush=True,
            )
            if i % 25 == 0:
                dst.write_text(json.dumps(results, ensure_ascii=False, indent=1))
    dst.write_text(json.dumps(results, ensure_ascii=False, indent=1))
    counts: dict[str, int] = {}
    for r in results:
        counts[r["outcome"]] = counts.get(r["outcome"], 0) + 1
    print("\noutcomes:", dict(sorted(counts.items(), key=lambda kv: -kv[1])))


if __name__ == "__main__":
    main()
