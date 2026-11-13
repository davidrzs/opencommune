"""Adapter for the content API of iomedia's municipal sites (Nuxt front end), as used by Nyon.

The listing is a Hydra collection from `/api/contents` on the commune's own host, for example
`type=documents_seances` filtered to the council's minutes and agendas, newest first. Each member
carries its files in `aio:documents[].url` (relative), its title, and its session in `seance_1`
(with `embed[]=seance_1`); the session date is preferred over the document's own `aio:dateFrom`.
The collection is paged through `hydra:view.next`. Recorded 2026-10-18 on www.nyon.ch.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import Mapping
from urllib.parse import urljoin

from ...schemas import AdapterStep
from .base import Link, ListingAdapter


def _date(value) -> dt.date | None:
    if isinstance(value, str) and len(value) >= 10:
        try:
            return dt.date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


class IomediaApiAdapter(ListingAdapter):
    name = "iomedia_api"

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
        keep = re.compile(step.text_regex, re.IGNORECASE) if step.text_regex else None
        links: list[Link] = []
        for item in data.get("hydra:member", []):
            title = (item.get("title") or "").strip()
            if keep and not keep.search(title):
                continue
            sessions = item.get("seance_1") or []
            session = sessions[0] if sessions and isinstance(sessions[0], dict) else {}
            date = _date(session.get("aio:dateFrom")) or _date(item.get("aio:dateFrom"))
            for doc in item.get("aio:documents") or []:
                url = doc.get("url") if isinstance(doc, dict) else None
                if not url or (doc.get("extension") or "pdf").lower() != "pdf":
                    continue
                links.append(Link(url=urljoin(base_url, url), text=title, date=date))
        return links

    def next_url(
        self, content: str, url: str, step: AdapterStep, headers: Mapping[str, str] | None = None
    ) -> str | None:
        following = (json.loads(content).get("hydra:view") or {}).get("next")
        return urljoin(url, following) if following else None
