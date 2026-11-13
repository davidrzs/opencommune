"""Carry discovery-probe results into the coverage register.

Usage: uv run python scripts/probe_to_register.py [--iweb iweb.json] [--generic generic.json]
                                                  [--date YYYY-MM-DD] [--apply]

Only rows that stand at `not_examined` or `blocked_network` change; every other status stays.
A hit (a listing the crawler could read, or a page named after the minutes) becomes `candidate`
with one publication that names the listing URL and what the probe saw. The GOViS variant that
renders its pages from the robots-disallowed `/route/` becomes `blocked_js`. Every other result
keeps its status and gets a probe note (the date is in `checked`), so the next examiner knows
what was tried. Without
`--apply` the script only prints what it would change.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from collections import Counter
from pathlib import Path

from opencommune.register import Publication, RegisterEntry, load_register, write_register

# The council a listing belongs to, from words in its URL or title; the first match wins.
_BODY_HINTS = (
    (
        re.compile(
            r"einwohnerrat|parlament|stadtrat-?sitzung|grosser-gemeinderat"
            r"|conseil-(communal|general|municipal|de-ville)|consiglio|legislativ",
            re.IGNORECASE,
        ),
        "parliament",
    ),
    (re.compile(r"versammlung|assembl|urversammlung|bezirksgemeinde", re.IGNORECASE), "assembly"),
    (
        re.compile(
            r"stadtrat|gemeinderat|municipalit|beschl|conseil-administratif|municipio",
            re.IGNORECASE,
        ),
        "executive",
    ),
)


def body_from_slug(text: str) -> str:
    """The council named in a URL or title; an assembly when nothing matches."""
    for rx, body in _BODY_HINTS:
        if rx.search(text):
            return body
    return "assembly"


CHANGEABLE = ("not_examined", "blocked_network")
UNREACHABLE: dict[int, str] = {}  # bfs id -> reason, from an `--unreachable` file
IWEB_HITS = {
    "sessions_minutes": "minutes",
    "sessions_decisions": "decisions",
    "page_minutes": "minutes",
    "page_decisions": "decisions",
}


PROBE = "Automated probe: "  # the start of every note this script writes; `checked` holds the date


def _note(entry: RegisterEntry, text: str) -> None:
    """Replace an earlier probe note, keep every other note."""
    kept = [
        n.strip()
        for n in (entry.notes or "").split(";")
        if n.strip()
        and not n.strip().startswith((PROBE.strip(), "probe ", "i-web hosting network"))
    ]
    entry.notes = "; ".join([*kept, PROBE + text]) if kept else PROBE + text


def apply_iweb(entry: RegisterEntry, res: dict, day: dt.date) -> str:
    outcome = res.get("outcome")
    entry.reachable = outcome != "unreachable"
    if outcome in IWEB_HITS and res.get("config"):
        kind = IWEB_HITS[outcome]
        url = res["config"]["listing_urls"][0]
        if outcome.startswith("sessions"):
            docs = res["session_docs"][kind]
            sample = docs[0]["text"] if docs else ""
            how = (
                f"Automated probe: /sitzung lists {res['sessions']} sessions since {res['sessions_from'][:4]}; "
                f"{kind} attached to the session pages as '{sample}'"
            )
        else:
            page = max(res["pages"], key=lambda p: p[f"{kind}_dated"])
            how = (
                f"Automated probe: page '{page['title']}' with {page[f'{kind}_dated']} dated {kind} links, "
                f"e.g. '{page['samples'][0]}'"
            )
        entry.status = "candidate"
        entry.checked, entry.checked_by = day, "scripts/probe_iweb.py (unverified)"
        entry.publications = [
            Publication(
                body=res.get("body") or body_from_slug(url),
                kind=kind,
                status="candidate",
                listing_url=url,
                **{"from": res["sessions_from"][:4] if res.get("sessions_from") else None},
                to=res.get("sessions_to"),
                how=how,
            )
        ]
        _note(entry, "i-web session module read")
        return "candidate"
    if outcome == "page_dated_links" and res.get("config"):
        page = max(res["pages"], key=lambda p: p.get("dated_links", 0))
        entry.status = "candidate"
        entry.checked, entry.checked_by = day, "scripts/probe_iweb.py (unverified)"
        entry.publications = [
            Publication(
                body=res.get("body") or body_from_slug(page["url"] + " " + page["title"]),
                kind="minutes",
                status="candidate",
                listing_url=page["url"],
                how=(
                    f"Automated probe: page '{page['title']}' with {page['dated_links']} dated document "
                    f"links, e.g. '{page['samples'][0]}'; kind and filter to be set by the reviewer"
                ),
            )
        ]
        _note(entry, "i-web content page with dated attachments")
        return "candidate"
    if entry.status == "blocked_network":
        entry.status = "not_examined"  # the hosting network answers again
    entry.checked, entry.checked_by = day, "scripts/probe_iweb.py (unverified)"
    if outcome == "unreachable":
        _note(entry, "homepage did not answer")
    elif outcome in ("sessions_without_documents", "sessions_empty"):
        titles = ", ".join(res.get("session_titles") or [])[:120]
        _note(
            entry,
            f"/sitzung lists {res.get('sessions', 0)} sessions since "
            f"{(res.get('sessions_from') or '')[:4]} ({titles}); the newest three carry no minutes "
            "or decision list; /sitemap names no protocol page",
        )
    elif outcome == "page_undated":
        page = res["pages"][0]
        _note(
            entry,
            f"page '{page['title']}' carries {page['minutes'] + page['decisions']} "
            f"protocol-like links without parseable dates: {page['url']}",
        )
    else:
        _note(entry, "no session module and no protocol page on /sitemap")
    return "note"


def apply_generic(entry: RegisterEntry, res: dict, day: dt.date) -> str:
    outcome = res.get("outcome") or ("unreachable" if res.get("vendor") == "unreachable" else "")
    entry.reachable = outcome != "unreachable"
    by = "scripts/probe_vendors.py (unverified)"
    tested = res.get("pages_tested") or []
    if res.get("pattern") and res.get("listing_url"):
        newest = res.get("newest_session")
        if res["pattern"] == "wp_media":
            how = (
                f"Automated probe: WordPress media endpoint answers; {res['sessions']} files match, "
                f"newest {newest}, e.g. '{res['session_text']}'"
            )
        else:
            how = (
                f"Automated probe: {res['sessions']} dated PDF links on the page, newest {newest}, "
                f"e.g. '{res['session_text']}'"
            )
        kind = "decisions" if "beschl" in (res.get("session_text") or "").lower() else "minutes"
        entry.status = "candidate"
        entry.checked, entry.checked_by = day, by
        entry.publications = [
            Publication(
                body=body_from_slug(res["listing_url"] + " " + (res.get("session_text") or "")),
                kind=kind,
                status="candidate",
                listing_url=res["listing_url"],
                to=str(newest)[:10] if newest else None,
                how=how + "; body guessed from the URL",
            )
        ]
        _note(entry, f"{res['pattern']}")
        return "candidate"
    entry.checked, entry.checked_by = day, by
    if outcome in ("protocol_page_dated_links", "protocol_page_undated", "protocol_page_no_pdfs"):
        page = max(
            (p for p in tested if p.get("protocol_page")),
            key=lambda p: (p.get("dated_links") or 0, p.get("pdfs") or 0),
        )
        if outcome == "protocol_page_dated_links":
            how = (
                f"Automated probe: page '{page['text']}' has {page.get('dated_links')} dated document links "
                "whose URLs do not end in .pdf; needs a selector"
            )
        elif outcome == "protocol_page_undated":
            how = (
                f"Automated probe: page '{page['text']}' has {page.get('pdfs') or 0} PDF links, none with a "
                "date the parser reads; needs a look"
            )
        else:
            how = (
                f"Automated probe: page '{page['text']}' names the minutes but links no PDF "
                "(subpages or JavaScript); needs a look"
            )
        entry.status = "candidate"
        entry.publications = [
            Publication(
                body=body_from_slug(page["url"] + " " + page["text"]),
                kind="minutes",
                status="candidate",
                listing_url=page["url"],
                how=how,
            )
        ]
        _note(entry, f"{outcome}")
        return "candidate"
    if outcome == "govis_route_js":
        entry.status = "blocked_js"
        _note(
            entry,
            "GOViS variant that renders page content from /route/, which robots.txt "
            "disallows; only the vendor or the commune can open it",
        )
        return "blocked_js"
    if outcome == "unreachable":
        reason = UNREACHABLE.get(res["bfs"], "")
        text = {
            "dns": "the website address does not resolve (stale address in the commune list?)",
            "robots": "robots.txt disallows the site root",
            "connect-timeout": "connection timed out",
            "read-timeout": "the server did not answer in time",
        }.get(reason)
        if not text and reason.startswith("http 403"):
            text = "the server answers 403 to the crawler"
        elif not text and reason.startswith("http"):
            text = f"the homepage answers {reason.upper()}"
        elif not text and "ConnectError" in reason:
            text = "TLS certificate error (hostname mismatch or incomplete chain)"
        elif not text and reason == "ok-now":
            text = "the homepage did not answer during the run but does now; probe again"
        _note(entry, f"{text or 'homepage did not answer'}")
    elif outcome == "js_home":
        _note(entry, "home page carries no navigation without JavaScript")
    elif outcome == "no_candidate_pages":
        _note(entry, "no link mentioning minutes or a council on the home page")
    else:
        urls = ", ".join(p["url"] for p in tested[:3])
        _note(entry, f"no dated protocol PDFs on {len(tested)} pages tested ({urls})")
    return "note"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--iweb", type=Path)
    ap.add_argument("--generic", type=Path)
    ap.add_argument("--unreachable", type=Path, help="reasons per site from a follow-up check")
    ap.add_argument("--date", type=dt.date.fromisoformat, default=dt.date.today())
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if args.unreachable:
        UNREACHABLE.update(
            {r["bfs"]: r["reason"] for r in json.loads(args.unreachable.read_text())}
        )
    register = load_register()
    by_bfs = {e.bfs_id: e for e in register}
    counts: Counter[str] = Counter()
    skipped: Counter[str] = Counter()
    for path, fn in ((args.iweb, apply_iweb), (args.generic, apply_generic)):
        if not path:
            continue
        for res in json.loads(path.read_text()):
            entry = by_bfs.get(res["bfs"])
            if entry is None:
                skipped["not in register"] += 1
                continue
            if entry.status not in CHANGEABLE:
                skipped[f"left alone ({entry.status})"] += 1
                continue
            counts[f"{fn.__name__}: {fn(entry, res, args.date)}"] += 1
    print("changes:", dict(counts))
    print("skipped:", dict(skipped))
    print("register statuses:", dict(Counter(e.status for e in register).most_common()))
    if args.apply:
        written = write_register(register)
        print(f"wrote {len(written)} files")
    else:
        print("dry run; pass --apply to write")


if __name__ == "__main__":
    main()
