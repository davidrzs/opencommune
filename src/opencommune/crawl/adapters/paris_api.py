"""Adapter for CMI's Paris/RIS parliament API as used by the Gemeinderat of the City of Zurich.

The listing "page" is the XML response of `/api/sitzung/searchdetails`; every session carries a
document list, and the one whose Kategorie matches the step's text_regex (default "Protokoll") is
downloadable at `/dokumente/{FileID}`. Documented at https://opendatazurich.github.io/paris-api/.
"""

from __future__ import annotations

import datetime as dt
import re
import xml.etree.ElementTree as ET
from urllib.parse import urlencode, urljoin

from ...schemas import AdapterStep, SourceConfig
from .base import Link, ListingAdapter

YEAR_LIMIT = 200  # hits per one-year session query; the Gemeinderat meets about 50 times a year


def _local(tag: str) -> str:
    return tag.split("}")[-1]


def _child(el: ET.Element, name: str) -> ET.Element | None:
    return next((c for c in el if _local(c.tag) == name), None)


class ParisApiAdapter(ListingAdapter):
    name = "paris_api"

    def listing_urls(self, source: SourceConfig) -> list[str]:
        """Session queries for the recent past, one per calendar year, newest first.

        One query over ten years with m=1000 answers HTTP 500 (2026-10-18); a year holds about 50
        sessions (7 MB of XML, mostly audio entries), well inside YEAR_LIMIT hits."""
        days = source.adapter_config.since_days or 180
        today = dt.date.today()
        start = today - dt.timedelta(days=days)
        base = source.listing_urls[0]
        urls = []
        for year in range(today.year, start.year - 1, -1):
            first = max(start, dt.date(year, 1, 1))
            last = min(today, dt.date(year, 12, 31))
            q = (
                f'sitzungsdatum_start > "{first.isoformat()} 00:00:00" and '
                f'sitzungsdatum_start < "{last.isoformat()} 23:59:59" '
                "sortBy sitzungsdatum_start/sort.descending"
            )
            urls.append(f"{base}?{urlencode({'q': q, 'l': 'de-CH', 'm': YEAR_LIMIT})}")
        return urls

    def extract_links(
        self,
        html: str,
        base_url: str,
        step: AdapterStep,
        date_regex: str | None,
        date_order: str,
        parent: Link | None = None,
    ) -> list[Link]:
        category = re.compile(step.text_regex or "Protokoll", re.IGNORECASE)
        root = ET.fromstring(html)
        links: list[Link] = []
        for hit in root:
            session = _child(hit, "Sitzung")
            if session is None:
                continue
            title = (
                (_child(session, "Titel").text or "").strip()
                if _child(session, "Titel") is not None
                else ""
            )
            datum = _child(session, "Datum")
            date = None
            if datum is not None:
                start = _child(datum, "Start")
                if start is not None and start.text:
                    date = dt.date.fromisoformat(start.text[:10])
            docs = _child(session, "Dokumente")
            for doc in list(docs) if docs is not None else []:
                kat = _child(doc, "Kategorie")
                file = _child(doc, "File")
                if kat is None or file is None or not category.search(kat.text or ""):
                    continue
                file_id = file.get("ID")
                if not file_id:
                    continue
                links.append(
                    Link(
                        url=urljoin(base_url, f"/dokumente/{file_id}"),
                        text=f"Gemeinderat, {title} vom {date.strftime('%d.%m.%Y') if date else '?'}: {file.get('FileName', '')}",
                        date=date,
                    )
                )
        return links
