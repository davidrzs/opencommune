"""Adapter for the CMI Axioma session backend of the Stadtrat of Bern.

The listing is the JSON of `sitzungen_data_server.php` for one calendar year (`dateFrom`,
`dateTo` as dd.mm.yyyy), `{recordsTotal, data: [session]}`. A session has `Datum.Start` (ISO)
and `Dokumente.Dokument` (one object or a list); each document has a `Kategorie` (Protokoll,
Traktandenliste, Antrag, Beilage, ...) and `File["@attributes"]["ID"]`, downloadable at
`/de/dokumente/{ID}` (checked 2026-10-18: application/pdf). The step's text_regex selects the
categories, by default the minutes.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from urllib.parse import urlencode, urljoin

from ...schemas import AdapterStep, SourceConfig
from .base import Link, ListingAdapter

SESSIONS_PER_YEAR = 450  # params[length]; the Stadtrat meets about 25 times a year


def _as_list(value) -> list:
    if not value:
        return []
    return value if isinstance(value, list) else [value]


class BernAxiomaAdapter(ListingAdapter):
    name = "bern_axioma"

    def listing_urls(self, source: SourceConfig) -> list[str]:
        """One query per calendar year back to since_days, newest first."""
        days = source.adapter_config.since_days or 365
        today = dt.date.today()
        first_year = (today - dt.timedelta(days=days)).year
        base = source.listing_urls[0]
        return [
            f"{base}?"
            + urlencode(
                {
                    "dateFrom": f"01.01.{year}",
                    "dateTo": f"31.12.{year}",
                    "params[length]": SESSIONS_PER_YEAR,
                }
            )
            for year in range(today.year, first_year - 1, -1)
        ]

    def extract_links(
        self,
        html: str,
        base_url: str,
        step: AdapterStep,
        date_regex: str | None,
        date_order: str,
        parent: Link | None = None,
    ) -> list[Link]:
        category = re.compile(step.text_regex or r"^Protokoll$", re.IGNORECASE)
        links: list[Link] = []
        for session in json.loads(html).get("data") or []:
            start = ((session.get("Datum") or {}).get("Start") or "")[:10]
            try:
                date = dt.date.fromisoformat(start)
            except ValueError:
                date = None
            for doc in _as_list((session.get("Dokumente") or {}).get("Dokument")):
                file = (
                    ((doc.get("File") or {}).get("@attributes") or {})
                    if isinstance(doc, dict)
                    else {}
                )
                if not file.get("ID") or not category.search(str(doc.get("Kategorie") or "")):
                    continue
                title = str(doc.get("Titel") or file.get("FileName") or "").strip()
                links.append(
                    Link(
                        url=urljoin(base_url, f"/de/dokumente/{file['ID']}"), text=title, date=date
                    )
                )
        return links
