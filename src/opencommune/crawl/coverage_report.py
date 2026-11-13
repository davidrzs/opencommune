"""How deep the archive goes per commune, read from the database and the crawl state; no network
requests.

Run: opencommune coverage-report --output data/reports/coverage
Catalogue counts are unique primary-attributed PDFs. Queue counts are URLs and
can overlap across collectors. A drained queue is never proof of completeness.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

from sqlalchemy.engine import make_url

from ..communes import load_communes
from ..config import settings
from ..register import load_register
from . import access, cooldown, linked_archive, wordpress

ACTIONS = {
    "discover_missing": "Find a public archive / configure a source",
    "review_shallow_scope": "Inspect discovery scope of a shallow archive",
    "resume_downloads": "Drain discovered PDF URLs",
    "continue_discovery": "Continue queued archive pages",
    "resolve_failures": "Review checkpoint failures or discovery limits",
    "resolve_access": "Review current source access restrictions",
    "inspect_untracked": "Inspect collection without a resumable checkpoint",
    "review_recent_range": "Check for older archive sections",
    "monitor": "Monitor configured scope; completeness unproven",
}


def catalogue_rows(connection, today):
    """One aggregate query; unknown/future dates cannot imply historical coverage."""
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        """SELECT commune_bfs_id, count(*) AS pdfs,
        sum(CASE WHEN date(source_date) <= :today THEN 1 ELSE 0 END) AS dated_pdfs,
        min(CASE WHEN date(source_date) <= :today THEN source_date END) AS oldest_date,
        max(CASE WHEN date(source_date) <= :today THEN source_date END) AS newest_date,
        sum(CASE WHEN date(source_date) > :today THEN 1 ELSE 0 END) AS future_dated_pdfs,
        max(indexed_at) AS catalogue_indexed_at
        FROM pdf_catalog GROUP BY commune_bfs_id""",
        {"today": today.isoformat()},
    )
    return {row["commune_bfs_id"]: dict(row) for row in rows}


def checkpoint(family, state):
    """Separate undiscovered pages, unattempted files, failures and held URLs."""
    documents = state.get("documents", {})
    downloads = state.get("downloads", {})
    pages = state.get("pages", {})
    reviews = state.get("review_documents", {})
    discovery = state.get("discovery", {})
    failures = [v for v in downloads.values() if v.get("status") == "failed"]
    page_failures = [v for v in pages.values() if v.get("status") == "failed"]
    unattempted = sum(url not in downloads and url not in reviews for url in documents)
    if family == "linked_archive":
        pending_pages = discovery.get(
            "unvisited", sum(u not in pages for u in state.get("frontier", {}))
        )
    else:
        pending_pages = len(state.get("pending", []))
    limits = sum(discovery.get(k, 0) for k in ("depth_limited", "capacity_limited"))
    result = dict(
        family=family,
        status=state.get("status", "recorded"),
        checked_at=state.get("updated_at"),
        refreshed_at=state.get("refreshed_at"),
        candidate_urls=len(documents),
        held_urls=sum(v.get("status") == "held" for v in downloads.values()),
        unattempted_urls=unattempted,
        failed_urls=len(failures),
        non_pdf_urls=sum(v.get("status") == "not_pdf" for v in downloads.values()),
        review_urls=len(reviews),
        pending_pages=pending_pages,
        failed_pages=len(page_failures),
        discovery_limits=limits,
        failure_kinds=dict(Counter(v.get("kind", "unknown") for v in failures + page_failures)),
    )
    result["configured_scope_drained"] = (
        not any(
            result[k]
            for k in (
                "unattempted_urls",
                "failed_urls",
                "review_urls",
                "pending_pages",
                "failed_pages",
                "discovery_limits",
            )
        )
        and (bool(pages) or bool(documents))
        and result["status"] not in {"blocked", "review", "listing_error", "running"}
    )
    return result


def classify(row, shallow_limit, today):
    """Transparent triage rules, not a completeness score or automatic scheduler."""
    sources = row["collectors"]
    resumable = [s for s in sources if s["family"] != "curated"]
    available = resumable
    signals = []
    if row["pdfs"] <= shallow_limit:
        signals.append("no_pdfs" if not row["pdfs"] else "few_pdfs")
    if row["pdfs"] and row["dated_pdfs"] < row["pdfs"]:
        signals.append("incomplete_date_metadata")
    if row["active_access"] or row["cooldown_until"]:
        signals.append("access_observation")
    errors = any(
        s.get("checkpoint_error")
        or s.get("status") in {"blocked", "review", "listing_error"}
        or any(
            s.get(k, 0) for k in ("failed_urls", "failed_pages", "review_urls", "discovery_limits")
        )
        for s in available
    )
    if errors:
        signals.append("checkpoint_failures_or_limits")
    # Saved stop conditions need review before recommending more requests. They
    # are not proof of a permanent restriction, and must not hide another collector.
    healthy = [
        s
        for s in available
        if s.get("status") not in {"blocked", "listing_error", "review"}
        and not s.get("failure_kinds", {}).get("robots")
        and not s.get("checkpoint_error")
    ]
    if row["cooldown_until"]:
        action = "resolve_access"
    elif any(s.get("unattempted_urls", 0) for s in healthy):
        action = "resume_downloads"
    elif any(s.get("pending_pages", 0) or s.get("status") == "not_started" for s in healthy):
        action = "continue_discovery"
    elif row["active_access"]:
        action = "resolve_access"
    elif errors:
        action = "resolve_failures"
    elif sources and not resumable:
        action = "inspect_untracked"
    elif not sources:
        action = "discover_missing" if not row["pdfs"] else "inspect_untracked"
    elif not all(s.get("configured_scope_drained") for s in available):
        action = "inspect_untracked"
    elif row["pdfs"] <= shallow_limit:
        action = "review_shallow_scope"
    elif (
        row["dated_pdfs"] / row["pdfs"] >= 0.8
        and row["oldest_date"]
        and int(row["oldest_date"][:4]) >= today.year - 2
    ):
        action = "review_recent_range"
        signals.append("recent_known_dates_only")
    else:
        action = "monitor"
    row.update(action=action, signals=signals)
    return row


def build_report(
    connection,
    entries,
    configured,
    data_dir,
    *,
    today,
    observations=None,
    cooldowns=None,
    shallow_limit=10,
):
    counts = catalogue_rows(connection, today)
    observations, cooldowns = observations or {}, cooldowns or {}
    rows = []
    for entry in entries:
        count = counts.get(entry.bfs_id, {})
        collectors = []
        for family in sorted(configured.get(entry.bfs_id, set())):
            path = data_dir / "discovery" / family / f"{entry.bfs_id}.json"
            if family == "curated":
                source = dict(family=family, status="no_checkpoint")
            elif not path.exists():
                source = dict(family=family, status="not_started")
            else:
                try:
                    state = json.loads(path.read_text())
                    if state.get("bfs_id") != entry.bfs_id:
                        raise ValueError("Wrong checkpoint identity")
                    source = checkpoint(family, state)
                except (OSError, ValueError, TypeError, AttributeError):
                    source = dict(family=family, status="unreadable", checkpoint_error=True)
            collectors.append(source)
        row = dict(
            bfs_id=entry.bfs_id,
            name=entry.name,
            canton=entry.canton,
            vendor=entry.vendor or "unknown",
            pdfs=count.get("pdfs", 0),
            dated_pdfs=count.get("dated_pdfs", 0),
            oldest_date=count.get("oldest_date"),
            newest_date=count.get("newest_date"),
            future_dated_pdfs=count.get("future_dated_pdfs", 0),
            catalogue_indexed_at=count.get("catalogue_indexed_at"),
            collectors=collectors,
            active_access=observations.get(entry.bfs_id, []),
            cooldown_until=cooldowns.get(entry.bfs_id),
        )
        rows.append(classify(row, shallow_limit, today))
    order = {name: n for n, name in enumerate(ACTIONS)}
    rows.sort(key=lambda r: (order[r["action"]], r["pdfs"], r["canton"], r["name"]))
    groups = Counter((r["vendor"], r["action"]) for r in rows)
    return dict(
        generated_at=dt.datetime.now(dt.UTC).isoformat(),
        as_of_date=today.isoformat(),
        shallow_limit=shallow_limit,
        summary=dict(
            communes=len(rows),
            communes_with_pdfs=sum(r["pdfs"] > 0 for r in rows),
            pdfs=sum(r["pdfs"] for r in rows),
            dated_pdfs=sum(r["dated_pdfs"] for r in rows),
            actions=dict(Counter(r["action"] for r in rows)),
            unregistered_catalogue_bfs_ids=sorted(set(counts) - {r["bfs_id"] for r in rows}),
        ),
        platform_actions=[
            dict(vendor=v, action=a, communes=n) for (v, a), n in groups.most_common()
        ],
        communes=rows,
    )


def markdown(report):
    summary = report["summary"]
    text = [
        "# Archive coverage and next actions",
        "",
        f"Snapshot: {report['generated_at']}",
        "",
        (
            f"**{summary['communes_with_pdfs']:,} communes with {summary['pdfs']:,} PDFs.** "
            f"{summary['dated_pdfs']:,} PDFs have a non-future source date."
        ),
        "",
        (
            "Dates come from the catalogue, never download timestamps or guessed filename years. "
            "They describe dated documents only. Missing dates are unknown; gaps between dates are not proof of missing files. "
            "A drained queue covers its configured scope, not necessarily the entire municipal archive. "
            "Queue counts are URLs, not unique PDFs. Checkpoints are sampled individually while jobs may run."
        ),
        "",
        (
            "Priority is a triage rule, not a completeness score. Access observations may affect only one source path; "
            "remaining work on other paths is still shown. `running` is saved state, not proof of a live process."
        ),
        "",
        "| Next action | Communes |",
        "| --- | ---: |",
    ]
    text += [f"| {ACTIONS[a]} | {n} |" for a, n in summary["actions"].items()]
    text += [
        "",
        "## Shared-platform opportunities",
        "",
        "| Platform | Action | Communes |",
        "| --- | --- | ---: |",
    ]
    text += [
        f"| {g['vendor']} | {ACTIONS[g['action']]} | {g['communes']} |"
        for g in report["platform_actions"][:25]
    ]
    for action, label in ACTIONS.items():
        candidates = [r for r in report["communes"] if r["action"] == action]
        if not candidates:
            continue
        text += [
            "",
            f"## {label}",
            "",
            "First 20, ordered by PDF count. Full inventory is in coverage.json.",
            "",
            "| BFS | Commune | Platform | PDFs | Dated | Oldest / newest known | Unattempted URLs | Pending pages |",
            "| --- | --- | --- | ---: | ---: | --- | ---: | ---: |",
        ]
        for r in candidates[:20]:
            text.append(
                f"| {r['bfs_id']} | {r['name']} ({r['canton']}) | {r['vendor']} | {r['pdfs']} | "
                f"{r['dated_pdfs']} | {r['oldest_date'] or '?'} / {r['newest_date'] or '?'} | "
                f"{sum(s.get('unattempted_urls', 0) for s in r['collectors'])} | "
                f"{sum(s.get('pending_pages', 0) for s in r['collectors'])} |"
            )
    return "\n".join(text) + "\n"


def write(output: Path, shallow_limit: int = 10) -> dict:
    """Write coverage.json and coverage.md to `output`; return the summary. Raises ValueError when
    the database is not a SQLite file."""
    url = make_url(settings.database_url)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        raise ValueError("the coverage report reads a file-backed SQLite catalogue")
    entries = load_register()
    configured = defaultdict(set)
    for family, sources in [
        ("linked_archive", linked_archive.load_sources()),
        ("wordpress", wordpress.load_sources()),
        ("curated", load_communes()),
    ]:
        for source in sources:
            configured[source.bfs_id].add(family)
    for entry in entries:
        if entry.vendor == "i-web" and entry.website:
            configured[entry.bfs_id].add("iweb")
    observations = {
        bfs_id: sorted({site["status"] for site in sites if not access.stale(site)})
        for bfs_id, sites in access.by_commune(entries).items()
    }
    cooldowns = {}
    for entry in entries:
        if entry.website:
            try:
                entry_cooldown = cooldown.active(entry.website)
                if entry_cooldown:
                    cooldowns[entry.bfs_id] = entry_cooldown["until_utc"]
            except cooldown.CooldownStateError:
                cooldowns[entry.bfs_id] = "unreadable"
    with sqlite3.connect(
        Path(url.database).resolve().as_uri() + "?mode=ro", uri=True, timeout=10
    ) as connection:
        report = build_report(
            connection,
            entries,
            configured,
            settings.data_dir,
            today=dt.date.today(),
            observations=observations,
            cooldowns=cooldowns,
            shallow_limit=shallow_limit,
        )
    output.mkdir(parents=True, exist_ok=True)
    for name, content in [
        ("coverage.json", json.dumps(report, ensure_ascii=False, indent=2) + "\n"),
        ("coverage.md", markdown(report)),
    ]:
        target = output / name
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(content)
        temporary.replace(target)
    return report["summary"]
