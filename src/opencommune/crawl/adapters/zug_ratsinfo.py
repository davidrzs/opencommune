"""Adapter for the Stadt Zug "ratsinfo" JSON API (https://ratsinfo.stadtzug.ch/api/).

Three hops, all JSON: meetings -> agenda items of one meeting -> published documents of the
"Wortprotokoll" business -> the PDF of type Protokoll. The step's text_regex on hop one selects the
committee by meeting title (for example "GGR").
"""

from __future__ import annotations

import datetime as dt
import json
import re
from urllib.parse import urljoin

from ...schemas import AdapterStep, SourceConfig
from .base import Link, ListingAdapter
from .html_links import parse_date

_PROT_DATE = re.compile(r"(20\d{2})(\d{2})(\d{2})")


class ZugRatsinfoAdapter(ListingAdapter):
    name = "zug_ratsinfo"

    def listing_urls(self, source: SourceConfig) -> list[str]:
        return [urljoin(source.listing_urls[0], "/api/meetings")]

    def extract_links(
        self,
        html: str,
        base_url: str,
        step: AdapterStep,
        date_regex: str | None,
        date_order: str,
        parent: Link | None = None,
    ) -> list[Link]:
        data = json.loads(html)
        rows = data if isinstance(data, list) else data.get("results", [])
        today = dt.date.today()
        links: list[Link] = []
        if base_url.rstrip("/").endswith("/api/meetings"):
            committee = re.compile(step.text_regex or "GGR", re.IGNORECASE)
            for m in rows:
                if m.get("status") != "completed" or not committee.search(m.get("title", "")):
                    continue
                date = dt.date.fromisoformat(m["begin"][:10])
                if date > today:
                    continue
                links.append(
                    Link(
                        url=urljoin(base_url, f"/api/meetings/{m['id']}/agenda_items"),
                        text=m.get("title", ""),
                        date=date,
                    )
                )
        elif "/agenda_items" in base_url:
            for item in rows:
                kind = str(item.get("business_type_display", "")).lower()
                title = str(item.get("title", ""))
                if "wortprotokoll" not in kind and not re.match(r"^GGR Protokoll", title):
                    continue
                bid = item.get("business_id")
                if bid:
                    links.append(
                        Link(
                            url=urljoin(base_url, f"/api/businesses/{bid}/published_documents"),
                            text=item.get("title", ""),
                            date=parse_date(item.get("title", "")),
                        )
                    )
        elif "/published_documents" in base_url:
            for doc in rows:
                if doc.get("document_type_name") != "Protokoll" or not doc.get("file"):
                    continue
                m = _PROT_DATE.search(doc.get("title", ""))
                date = dt.date(int(m[1]), int(m[2]), int(m[3])) if m else None
                links.append(
                    Link(
                        url=urljoin(base_url, doc["file"]),
                        text=f"Grosser Gemeinderat Zug, {doc.get('title', '')}",
                        date=date,
                    )
                )
        return links
