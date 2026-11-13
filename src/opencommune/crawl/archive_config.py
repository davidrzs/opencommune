"""Turn a complete WordPress availability report into tracked archive sources."""

from __future__ import annotations

import json
import os
import tempfile
from collections import Counter
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import yaml

from ..communes import bfs_register
from ..config import settings
from ..register import load_register
from .iweb import clean_url, same_site
from .wordpress import ArchiveSourceConfig, load_sources, validate_sources


def _source_key(source: ArchiveSourceConfig) -> tuple:
    parts = urlsplit(source.listing_url)
    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)))
    endpoint = urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, query, ""))
    return source.bfs_id, source.website, endpoint


def configure_wordpress(report_path=None, output_path=None) -> dict:
    """Configure all available endpoints together, or leave the existing file untouched.

    A missing total is allowed: a validated PDF sample establishes availability,
    and the downloader discovers pagination independently. Report failures remain
    visible in the returned status counts; they do not become archive sources.
    """
    report_path = Path(report_path or settings.data_dir / "discovery/wordpress/probe.json")
    output_path = Path(output_path or settings.config_root / "archive-sources.yaml")
    report = json.loads(report_path.read_text())
    if not isinstance(report, dict):
        raise ValueError("WordPress report must be an object keyed by BFS ID")
    entries = [e for e in load_register() if e.vendor == "wordpress" and e.website]
    expected = {str(e.bfs_id): e for e in entries}
    missing = expected.keys() - report.keys()
    if missing:
        raise ValueError(f"incomplete WordPress report: missing {', '.join(sorted(missing))}")
    previous = {_source_key(source): source for source in load_sources(output_path)}
    identities = bfs_register()
    sources = []
    statuses = Counter()
    curated = 0
    for key, entry in expected.items():
        row = report[key]
        identity = identities.get(entry.bfs_id)
        if (
            not isinstance(row, dict)
            or type(row.get("bfs_id")) is not int
            or row["bfs_id"] != entry.bfs_id
            or row.get("website") != entry.website
            or row.get("canton") != entry.canton
            or identity is None
            or identity[1] != entry.canton
            or not isinstance(row.get("status"), str)
            or not row["status"]
        ):
            raise ValueError(f"{key}: report identity or status mismatch; probe again")
        statuses[row["status"]] += 1
        if row["status"] != "available":
            continue
        endpoint = row.get("endpoint")
        samples = row.get("sample_urls")
        if (
            not isinstance(endpoint, str)
            or clean_url(endpoint) is None
            or not same_site(endpoint, entry.website)
            or not isinstance(samples, list)
            or not samples
            or any(not isinstance(url, str) or clean_url(url) is None for url in samples)
        ):
            raise ValueError(f"{key}: invalid endpoint or PDF sample URLs; review required")
        parts = urlsplit(endpoint)
        # Keep the actual installation path and unrelated routing parameters, but
        # remove probe projections and filters so the archive covers all PDF media.
        query = [
            (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if k not in {"_fields", "per_page", "page", "mime_type", "search"}
        ]
        query.extend([("per_page", "100"), ("page", "1"), ("mime_type", "application/pdf")])
        listing_url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))
        source = ArchiveSourceConfig(
            bfs_id=entry.bfs_id, website=entry.website, listing_url=listing_url
        )
        prior = previous.get(_source_key(source))
        if prior is not None:
            source.document_url_prefixes = prior.document_url_prefixes.copy()
            source.attribution_note = prior.attribution_note
        sources.append(source)
        curated += entry.status == "configured"
    validate_sources(sources, entries)
    sources.sort(key=lambda source: (identities[source.bfs_id][1], identities[source.bfs_id][0]))
    content = yaml.safe_dump(
        [s.model_dump(mode="json") for s in sources], allow_unicode=True, sort_keys=False
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", dir=output_path.parent, prefix=f".{output_path.name}.", delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(content)
        os.replace(temporary, output_path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {
        "configured": len(sources),
        "already_curated": curated,
        "statuses": dict(sorted(statuses.items())),
        "checked": len(expected),
        "output_path": str(output_path),
    }
