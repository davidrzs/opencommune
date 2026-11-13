"""Offline API fixture for the UI tests; never contacts municipal sites.

It answers the endpoints the front end reads (server/API.md) from a few invented communes and
files, and filters and counts the files the way the API does: each facet with every filter except
its own.
"""

import datetime as dt
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

now = dt.datetime.now(dt.UTC).isoformat()
old = (dt.datetime.now(dt.UTC) - dt.timedelta(days=8)).isoformat()
RUN = "classify-65e415a748e2"


def access(status, stale=False):
    """One access observation for the commune's website."""
    return dict(
        status=status,
        checked_at=old if stale else now,
        restricted_at=old if stale else now if status == "restricted" else None,
        stale=stale,
        source_url="https://commune.example/",
        robots_url="https://commune.example/robots.txt",
    )


# bfs_id, name, register status, access observations
COMMUNES = [
    (1, "Aeugst am Albis", "blocked_robots", [access("restricted")]),
    (2, "Affoltern am Albis", "configured", [access("rate_limited")]),
    (3, "Bonstetten", "configured", [access("restricted", stale=True)]),
    (117, "Hinwil", "configured", []),
    (121, "Wetzikon", "blocked_robots", [access("restricted")]),
]
NAMES = {bfs: name for bfs, name, _, _ in COMMUNES}


FAMILY = dict(
    minutes="deliberation",
    decisions="deliberation",
    vote_result="deliberation",
    budget="money",
    accounts="money",
    invitation_agenda="proposals",
    proposal="proposals",
    member_request="proposals",
    regulation="rules",
    report="information",
    notice="information",
    plan_or_map="information",
    news="information",
    other="other",
    unclear="other",
)


def document(n, communes, sections=(), **fields):
    """A classified file with the API's fields; `sections` as (type, first, last, partly_unseen)."""
    sha = f"{n:064x}"
    year = fields.get("year")
    return dict(
        sha256=sha,
        title=fields.get("title"),
        body_name=fields.get("body_name"),
        first_seen="2026-09-01",
        listing_date=fields.get("listing_date"),
        date=fields.get("date"),
        year=year,
        years=[year] if year else [],
        page_count=fields.get("page_count", 40),
        pages_seen=min(fields.get("page_count") or 0, 150),
        run_id=RUN,
        body_kind=fields.get("body_kind", "executive"),
        languages=fields.get("languages", ["de"]),
        personal_data=False,
        sections=[
            dict(type=t, family=FAMILY[t], first_page=a, last_page=b, partly_unseen=u)
            for t, a, b, u in sections
        ],
        communes=[dict(bfs_id=b, name=NAMES[b], canton="ZH") for b in communes],
        original_url=f"/original/{sha}",
    )


DOCUMENTS = [
    # a meeting booklet with several sections
    document(
        1,
        [121],
        sections=[
            ("invitation_agenda", 1, 2, False),
            ("proposal", 3, 6, False),
            ("proposal", 7, 10, False),
            ("minutes", 11, 12, False),
            ("budget", 13, 40, False),
        ],
        title="Einladung zur Gemeindeversammlung",
        body_name="Gemeindeversammlung Wetzikon",
        date="2025-06-12",
        year=2025,
        body_kind="citizens_assembly",
    ),
    # no printed title, accounts without a date, shared with Hinwil, in two languages
    document(
        2,
        [117, 121],
        sections=[("accounts", 1, 150, False), ("report", 150, 220, True)],
        body_name="Stadt Wetzikon",
        year=2024,
        page_count=220,
        languages=["de", "fr"],
        body_kind="commune",
    ),
    # a bulletin in French: news around a budget
    document(
        3,
        [121],
        sections=[("news", 1, 8, False), ("budget", 9, 12, False), ("news", 13, 16, False)],
        title="Bulletin communal",
        listing_date="2024-11-05",
        year=2024,
        page_count=16,
        languages=["fr"],
        body_kind="commune",
    ),
    # nothing read: no title, no sections, no year
    document(4, [121], page_count=None, languages=[], body_kind="unknown"),
    # one regulation, a year but no date
    document(
        5,
        [121],
        sections=[("regulation", 1, 12, False)],
        title="Reglement über die Abfallentsorgung",
        year=2023,
        page_count=12,
    ),
] + [
    document(
        10 + i,
        [121],
        sections=[("budget" if i % 3 == 0 else "minutes", 1, 1 + i, False)],
        title=f"Protokoll {2000 + i}",
        body_name="Gemeinderat",
        date=f"{2000 + i}-05-0{1 + i % 9}",
        year=2000 + i,
        page_count=1 + i,
        body_kind="citizens_assembly" if i % 2 else "executive",
    )
    for i in range(20)
]


def matches(doc, filters, leave_out=None):
    """Whether the file passes every filter but `leave_out`."""
    for key, value in filters.items():
        if key == leave_out:
            continue
        if key == "commune" and int(value) not in [c["bfs_id"] for c in doc["communes"]]:
            return False
        if key == "section" and value not in [s["type"] for s in doc["sections"]]:
            return False
        if key == "family" and value not in [s["family"] for s in doc["sections"]]:
            return False
        if key == "body" and doc["body_kind"] != value:
            return False
        if key == "year" and str(doc["year"]) != value:
            return False
        if key == "q" and value.lower() not in (doc["title"] or "").lower():
            return False
    return True


def facet(docs, values, newest_first=False):
    """`[{value, count}]` over the files: values ascending (years newest first), null last."""
    counts = {}
    for doc in docs:
        for value in values(doc):
            counts[value] = counts.get(value, 0) + 1
    known = sorted((v for v in counts if v is not None), reverse=newest_first)
    order = known + ([None] if None in counts else [])
    return [dict(value=v, count=counts[v]) for v in order]


def documents(query):
    filters = {k: v[0] for k, v in query.items() if k not in ("offset", "limit") and v[0]}
    offset = int(query.get("offset", ["0"])[0])
    limit = min(int(query.get("limit", ["20"])[0]), 100)
    chosen = [d for d in DOCUMENTS if matches(d, filters)]
    # year descending with no year last, then date (else listing date) descending, then sha256
    chosen.sort(key=lambda d: d["sha256"])
    chosen.sort(key=lambda d: d["date"] or d["listing_date"] or "", reverse=True)
    chosen.sort(key=lambda d: (d["year"] is not None, d["year"] or 0), reverse=True)

    def others(key):
        return [d for d in DOCUMENTS if matches(d, filters, key)]

    return dict(
        total=len(chosen),
        offset=offset,
        limit=limit,
        facets=dict(
            years=facet(others("year"), lambda d: [d["year"]], newest_first=True),
            # a file without sections is in no entry
            sections=facet(others("section"), lambda d: {s["type"] for s in d["sections"]}),
            bodies=facet(others("body"), lambda d: [d["body_kind"]]),
        ),
        items=chosen[offset : offset + limit],
    )


def listed(bfs, name, status):
    """A row of the commune list."""
    held = sum(bfs in [c["bfs_id"] for c in d["communes"]] for d in DOCUMENTS)
    return dict(
        bfs_id=bfs,
        name=name,
        canton="ZH",
        language="de",
        website="https://commune.example",
        lat=None,
        lon=None,
        documents=held,
        register_status=status,
        register_note=None,
    )


def detail(bfs, name, status, observations):
    """The commune page: the list's row with the register entry and the access observations."""
    row = listed(bfs, name, status)
    register = dict(
        bfs_id=bfs,
        name=name,
        canton="ZH",
        status=status,
        website=row["website"],
        vendor=None,
        reachable=True,
        checked="2026-09-08",
        checked_by="listing review",
        notes=None,
        publications=[],
    )
    keys = ("bfs_id", "name", "canton", "language", "website", "lat", "lon", "documents")
    return {
        **{k: row[k] for k in keys},
        "vendor": None,
        "register": register,
        "access": observations,
        "holdings": holdings(bfs),
    }


def holdings(bfs):
    """Documents with a section of the family, per year; newest year first, then family."""
    counts = {}
    for d in DOCUMENTS:
        if d["year"] is None or bfs not in [c["bfs_id"] for c in d["communes"]]:
            continue
        for family in {s["family"] for s in d["sections"]}:
            counts[(d["year"], family)] = counts.get((d["year"], family), 0) + 1
    order = sorted(counts, key=lambda k: (-k[0], k[1]))
    return [dict(year=y, family=f, documents=counts[(y, f)]) for y, f in order]


RUNS = [
    dict(
        id=RUN,
        stage="classification",
        model="model-x",
        settings=dict(dpi=75, max_pages=150),
        note="Pages rendered at 75 dpi; at most 150 pages per document.",
        documents=len(DOCUMENTS),
    )
]


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urlsplit(self.path)
        path = url.path
        body = None
        if path == "/api/communes":
            body = [listed(bfs, name, status) for bfs, name, status, _ in COMMUNES]
        elif path.startswith("/api/communes/"):
            body = next(
                (detail(*c) for c in COMMUNES if str(c[0]) == path.rsplit("/", 1)[1]), None
            )
        elif path == "/api/documents":
            body = documents(parse_qs(url.query))
        elif path == "/api/runs":
            body = RUNS
        elif path == "/api/openapi.json":
            # the server's own description, saved from a running server
            body = json.loads((Path(__file__).parent / "openapi.json").read_text())
        if body is None:
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"detail": "not found"}')
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def log_message(self, *args):
        pass


HTTPServer(("127.0.0.1", 8002), Handler).serve_forever()
