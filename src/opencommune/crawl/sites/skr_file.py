"""Read public file URLs from the embedded skrListFileManager JSON widget.

The widget's x-data attribute starts with a JSON object followed by display
options. We decode that object only; no JavaScript is evaluated or requested.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

_CALL = "skrListFileManager("
_ROUTE = re.compile(r"/datei-download/([1-9][0-9]{0,17})/[a-z0-9][a-z0-9-]*", re.I)
_OPTIONS = re.compile(r"(?:,\s*'[A-Za-z]+'\s*,\s*'[A-Za-z]+'\s*)?\)")
_MAX_ATTRIBUTE = 1_000_000


def document_urls(soup: BeautifulSoup, listing: str) -> list[str]:
    """Return only same-origin, ID-matched download routes in observed widgets."""
    return sorted({entry["url"] for entry in widget_entries(soup, listing)})


def widget_entries(soup: BeautifulSoup, listing: str) -> list[dict]:
    """The widget entries whose URL is a same-origin, ID-matched download route, in widget order,
    each with its `url` made absolute (name, category and date as the widget gives them)."""
    base = urlsplit(listing)
    if base.scheme not in {"http", "https"} or not base.netloc:
        return []
    found: list[dict] = []
    seen: set[str] = set()
    for element in soup.select("[x-data]"):
        value = element.get("x-data", "")
        if not value.startswith(_CALL) or len(value) > _MAX_ATTRIBUTE:
            continue
        try:
            groups, offset = json.JSONDecoder().raw_decode(value[len(_CALL) :])
        except (ValueError, TypeError):
            continue
        tail = value[len(_CALL) + offset :].lstrip()
        if not isinstance(groups, dict) or not _OPTIONS.fullmatch(tail):
            continue
        for entries in groups.values():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict) or not isinstance(entry.get("url"), str):
                    continue
                raw = entry["url"]
                try:
                    parts = urlsplit(raw)
                except ValueError:
                    continue
                if parts.scheme or parts.netloc or parts.query or parts.fragment:
                    continue
                match = _ROUTE.fullmatch(parts.path)
                if not match or type(entry.get("id")) is not int or entry["id"] != int(match[1]):
                    continue
                url = urljoin(f"{base.scheme}://{base.netloc}/", raw)
                if url not in seen:
                    seen.add(url)
                    found.append({**entry, "url": url})
    return found
