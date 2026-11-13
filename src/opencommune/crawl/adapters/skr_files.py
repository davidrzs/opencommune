"""Adapter for the skrListFileManager widget (Kreuzlingen's parliament archive).

The page holds no document anchors: an Alpine.js `x-data="skrListFileManager({...}, 'date', 'desc')"`
attribute carries every file as JSON, `{"id", "name", "category", "date", "url": "/datei-download/<id>/<slug>"}`.
`sites.skr_file.widget_entries` decodes that object without running JavaScript. On Kreuzlingen's archive the `date`
is the council session the file belongs to (the agenda, minutes and messages of one session share it).
The step's text_regex selects on the name; exclude_regex sees name, category and URL.
"""

from __future__ import annotations

import datetime as dt
import re

from ...schemas import AdapterStep
from ..html_parse import parse_html
from ..sites.skr_file import widget_entries
from .base import Link, ListingAdapter


def _date(value) -> dt.date | None:
    if isinstance(value, str) and len(value) >= 10:
        try:
            return dt.date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


class SkrFilesAdapter(ListingAdapter):
    name = "skr_files"

    def extract_links(
        self,
        html: str,
        base_url: str,
        step: AdapterStep,
        date_regex: str | None,
        date_order: str,
        parent: Link | None = None,
    ) -> list[Link]:
        keep = re.compile(step.text_regex, re.IGNORECASE) if step.text_regex else None
        drop = re.compile(step.exclude_regex, re.IGNORECASE) if step.exclude_regex else None
        links: list[Link] = []
        for entry in widget_entries(parse_html(html), base_url):
            name = " ".join(str(entry.get("name") or "").split())
            category = str(entry.get("category") or "")
            if keep and not keep.search(name):
                continue
            if drop and drop.search(f"{name} {category} {entry['url']}"):
                continue
            links.append(Link(url=entry["url"], text=name, date=_date(entry.get("date"))))
        return links
