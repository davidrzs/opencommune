"""Pure, bounded sitemap link extraction for configured archive frontiers."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from urllib.parse import urlsplit

SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
MAX_XML_BYTES = 5 * 1024 * 1024


def _tag(local: str, namespace: str) -> str:
    return f"{{{namespace}}}{local}" if namespace else local


def sitemap_links(xml: str, listing: str, source) -> list[str]:
    """Return configured XML children or document pages from a sitemap index/urlset.

    Network access and persistence belong to the caller. Every result must pass the
    source's existing listing scope; an index may only introduce XML sitemap pages.
    """
    if not source.allows_listing(listing):
        raise ValueError("sitemap listing is outside the configured source scope")
    if len(xml.encode("utf-8")) > MAX_XML_BYTES or "<!DOCTYPE" in xml.upper():
        raise ValueError("sitemap XML is unsafe or too large")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ValueError("malformed sitemap XML") from exc
    if root.tag.startswith("{"):
        namespace, _, local = root.tag[1:].partition("}")
    else:
        namespace, local = "", root.tag
    if namespace not in {"", SITEMAP_NS} or local not in {"sitemapindex", "urlset"}:
        raise ValueError("expected a sitemapindex or urlset")
    item_tag = _tag("sitemap" if local == "sitemapindex" else "url", namespace)
    loc_tag = _tag("loc", namespace)
    items = root.findall(item_tag)
    if len(root) and not items:
        raise ValueError("sitemap entries have the wrong XML shape")
    found: dict[str, None] = {}
    for item in items:
        loc = item.find(loc_tag)
        if loc is None or not loc.text or not loc.text.strip():
            raise ValueError("sitemap entry lacks loc")
        url = loc.text.strip()
        if local == "sitemapindex":
            if urlsplit(url).hostname != urlsplit(listing).hostname or not urlsplit(
                url
            ).path.lower().endswith(".xml"):
                continue
        elif urlsplit(url).path.lower().endswith(".xml"):
            continue
        if source.allows_listing(url):
            found[url] = None
    return list(found)
