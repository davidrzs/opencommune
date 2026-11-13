"""Extract PDF links from Hoststar's embedded file-download widget data.

Hoststar pages render a ``Server.components`` JSON object in a script element.
This module parses that object as JSON; it never evaluates page JavaScript.
Callers must still check municipal attribution and document-host scope.
"""

from __future__ import annotations

import json
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from ..iweb import clean_url

ASSIGNMENT = "Server.components = "


def extract_pdf_urls(html: str, base_url: str) -> list[str]:
    """Return unique PDF URLs from file-download widgets in document order."""
    seen: set[str] = set()
    urls: list[str] = []
    for script in BeautifulSoup(html, "html.parser").find_all("script"):
        source = script.string or ""
        offset = source.find(ASSIGNMENT)
        if offset < 0:
            continue
        try:
            components, _ = json.JSONDecoder().raw_decode(
                source[offset + len(ASSIGNMENT) :].lstrip()
            )
        except json.JSONDecodeError:
            continue
        if not isinstance(components, dict):
            continue
        for widget in components.values():
            if not isinstance(widget, dict) or widget.get("type") != "widget.filedownload":
                continue
            data = widget.get("data")
            raw_url = data.get("url") if isinstance(data, dict) else None
            if not isinstance(raw_url, str):
                continue
            url = clean_url(urljoin(base_url, raw_url))
            if url is None or not urlsplit(url).path.lower().endswith(".pdf") or url in seen:
                continue
            seen.add(url)
            urls.append(url)
    return urls
