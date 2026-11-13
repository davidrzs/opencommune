"""Checks on the commune configuration beyond what the loader validates: `opencommune lint-communes`.

The loader rejects unknown keys and wrong types. This module adds what the crawler would only find
out on the first run: regexes and CSS selectors that do not compile, a `date_regex` without the three
groups `parse_date` reads, an adapter that is not registered, listing URLs that are not absolute or
carry a malformed `{a..b}` range, a BFS id or canton that disagrees with the snapshot, coordinates outside Switzerland, a missing `added` date, an
entry listed twice, and entries out of order (canton, then name).
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit

import soupsieve
from pydantic import ValidationError

from .communes import read_commune_items
from .crawl.adapters import get_adapter
from .schemas import CommuneConfig, SourceConfig

LAT_RANGE = (45.8, 47.9)
LON_RANGE = (5.9, 10.6)
_RANGE = re.compile(r"\{(\d+)\.\.(\d+)\}")
_CANTON = re.compile(r"^[A-Z]{2}$")


def lint_communes(
    path: Path | None = None, bfs: dict[int, tuple[str, str]] | None = None
) -> list[str]:
    """Every problem as one line; [] when the configuration is clean. `bfs` maps a BFS id to
    (official name, canton) and is None when the snapshot is not available."""
    problems: list[str] = []
    seen: dict[int, str] = {}
    for file, items in read_commune_items(path):
        order: list[tuple[str, str]] = []
        for i, item in enumerate(items):
            who = f"{file.name} entry {i + 1}"
            if isinstance(item, dict) and (item.get("name") or item.get("bfs_id")):
                who += f" ({item.get('name') or item.get('bfs_id')})"
            try:
                c = CommuneConfig.model_validate(item)
            except ValidationError as exc:
                details = "; ".join(
                    f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors()
                )
                problems.append(f"{who}: {details}")
                continue
            order.append((c.canton, c.name))
            if c.bfs_id in seen:
                problems.append(f"{c.bfs_id} {c.name}: listed twice (also in {seen[c.bfs_id]})")
            seen[c.bfs_id] = file.name
            problems.extend(f"{c.bfs_id} {c.name}: {p}" for p in check_commune(c, bfs))
        if order != sorted(order):
            problems.append(f"{file.name}: entries are not sorted by canton, then name")
    return problems


def check_commune(c: CommuneConfig, bfs: dict[int, tuple[str, str]] | None = None) -> list[str]:
    out: list[str] = []
    if c.added is None:
        out.append("no added date")
    if bfs is not None:
        official = bfs.get(c.bfs_id)
        if official is None:
            out.append("not in the BFS snapshot")
        else:
            name, canton = official
            if c.canton != canton:
                out.append(f"canton {c.canton}, BFS says {canton}")
            if c.name not in (name, name.split(" (")[0]):
                out.append(f"BFS name is {name}")
    elif not _CANTON.match(c.canton):
        out.append(f"canton {c.canton!r} is not a two-letter code")
    if c.lat is None or c.lon is None:
        out.append("no coordinates (lat, lon)")
    else:
        if not LAT_RANGE[0] <= c.lat <= LAT_RANGE[1]:
            out.append(f"lat {c.lat} outside {LAT_RANGE}")
        if not LON_RANGE[0] <= c.lon <= LON_RANGE[1]:
            out.append(f"lon {c.lon} outside {LON_RANGE}")
    if not c.website.startswith(("http://", "https://")):
        out.append(f"website {c.website!r} is not absolute")
    for k, source in enumerate(c.all_sources(), 1):
        label = f"source {k} ({source.adapter})"
        out.extend(f"{label}: {p}" for p in check_source(source, c.bfs_id))
    return out


def check_source(source: SourceConfig, bfs_id: int) -> list[str]:
    out: list[str] = []
    try:
        get_adapter(source.adapter)
    except KeyError as exc:
        out.append(str(exc.args[0]))
    for url in source.listing_urls:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            out.append(f"listing URL not absolute: {url}")
        ranges = _RANGE.findall(url)
        if len(ranges) > 1:
            out.append(f"more than one {{a..b}} range in {url}")
        for a, b in ranges:
            if int(a) > int(b):
                out.append(f"range {{{a}..{b}}} runs backwards in {url}")
    cfg = source.adapter_config
    if cfg.date_regex is not None:
        rx = _regex(cfg.date_regex, "date_regex", out)
        if rx is not None and rx.groups < 3:
            out.append(
                f"date_regex needs three groups (day, month, year, or year first with date_order ymd): {cfg.date_regex}"
            )
    for j, step in enumerate(cfg.steps, 1):
        for field in ("selector", "next_selector"):
            value = getattr(step, field)
            if value is None:
                continue
            try:
                soupsieve.compile(value)
            except soupsieve.SelectorSyntaxError as exc:
                out.append(
                    f"step {j} {field} does not parse: {value!r} ({str(exc).splitlines()[0]})"
                )
        if step.exclude_regex is not None and not (step.exclude_approved or "").strip():
            out.append(
                f"step {j} exclude_regex has no exclude_approved: every exclusion needs David's approval"
            )
        for field in ("url_regex", "text_regex", "exclude_regex"):
            value = getattr(step, field)
            if value is not None:
                _regex(value, f"step {j} {field}", out)
    return out


def _regex(pattern: str, label: str, out: list[str]) -> re.Pattern[str] | None:
    try:
        return re.compile(pattern)
    except re.error as exc:
        out.append(f"{label} does not compile: {pattern!r} ({exc})")
        return None
