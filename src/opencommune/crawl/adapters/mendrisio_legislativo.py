"""Adapter for the Consiglio comunale archive of Mendrisio (legislativo.mendrisio.ch).

The site is an Angular app over a public JSON API (routes from its bundle, recorded 2026-10-19):
`/api/public/legislations` lists the legislatures `[{id, period, current}]`, and
`/api/public/sessions?legislationId=N&page=P&size=S` pages their sessions
`{content: [session], hasNext, pageNumber}`. A session has `number` ("Seduta del 4 marzo 2013"),
`date` ("4 marzo 2013") and `documents[]` with `label` (Convocazione, Estratto risoluzioni,
Verbale), `filename` and `endpoint`, the download route (`/api/public/sessions/23/agenda`, checked
2026-10-19: application/pdf). Every document is dated by its session: file names carry typos and
issue dates ("72_2013_10_03_risoluzioni" for the session of 3 October 2016).

Two hops, told apart by the step `kind`: "legislations" yields one sessions page per legislature,
"sessions" (the default) yields the documents; the step's text_regex selects on the label.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

from ...schemas import AdapterStep
from .base import Link, ListingAdapter, excluded
from .html_links import parse_date

PAGE_SIZE = 100  # sessions per page; a legislature has 15 to 30


def _sessions_url(base_url: str, legislation: int, page: int = 0, size: int = PAGE_SIZE) -> str:
    query = urlencode({"legislationId": legislation, "page": page, "size": size})
    return urljoin(base_url, f"/api/public/sessions?{query}")


class MendrisioLegislativoAdapter(ListingAdapter):
    name = "mendrisio_legislativo"

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
        if step.kind == "legislations":
            return [
                Link(url=_sessions_url(base_url, item["id"]), text=str(item.get("period") or ""))
                for item in data
                if isinstance(item, dict) and type(item.get("id")) is int
            ]
        keep = re.compile(step.text_regex, re.IGNORECASE) if step.text_regex else None
        drop = re.compile(step.exclude_regex, re.IGNORECASE) if step.exclude_regex else None
        links: list[Link] = []
        for session in data.get("content") or []:
            title = " ".join(str(session.get("number") or "").split())
            date = parse_date(str(session.get("date") or ""), shapes=True)
            for doc in session.get("documents") or []:
                endpoint = doc.get("endpoint") if isinstance(doc, dict) else None
                label = str(doc.get("label") or "") if isinstance(doc, dict) else ""
                if not endpoint or (keep and not keep.search(label)):
                    continue
                text = f"{label} - {title}" if title else label
                if excluded(drop, f"{text} {doc.get('filename') or ''} {endpoint}"):
                    continue
                links.append(Link(url=urljoin(base_url, endpoint), text=text, date=date))
        return links

    def next_url(
        self, content: str, url: str, step: AdapterStep, headers: Mapping[str, str] | None = None
    ) -> str | None:
        if step.kind == "legislations":
            return None
        data = json.loads(content)
        if not isinstance(data, dict) or not data.get("hasNext"):
            return None
        query = parse_qs(urlsplit(url).query)
        legislation = int(query["legislationId"][0])
        size = int(query.get("size", [PAGE_SIZE])[0])
        return _sessions_url(url, legislation, int(data.get("pageNumber") or 0) + 1, size)
