"""Public Magnolia bulletin pages, from the municipality's published search client.

The caller explicitly configures the observed endpoint and allowed article paths.
No endpoint discovery, document metadata inference or rich-text interpretation.
"""

import json
import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from ..discovery import page_url

PAGE_SIZE = 10
MAX_OFFSET = 20_000


def offset(url: str) -> int | None:
    parts = urlsplit(url)
    if not re.fullmatch(r"/[a-z0-9-]+-ajax/bulletins", parts.path):
        return None
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    if len(pairs) != 2 or {k for k, _ in pairs} != {"startIndex", "maxResults"}:
        return None
    query = dict(pairs)
    value = query["startIndex"]
    if query["maxResults"] != str(PAGE_SIZE) or not re.fullmatch(r"[0-9]{1,5}", value):
        return None
    number = int(value)
    return number if number <= MAX_OFFSET and number % PAGE_SIZE == 0 else None


def links(payload: str, listing: str) -> list[str]:
    start = offset(listing)
    if start is None:
        raise ValueError("unreviewed bulletin request shape")
    data = json.loads(payload)
    rows = data.get("results") if isinstance(data, dict) else None
    if not isinstance(rows, list) or len(rows) > PAGE_SIZE:
        raise ValueError("invalid bulletin result list")
    found = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("pageURL"), str):
            raise ValueError("bulletin has no page URL")
        target = page_url(urljoin(listing, row["pageURL"]))
        if not target:
            raise ValueError("invalid bulletin page URL")
        if target not in found:
            found.append(target)
    if len(rows) == PAGE_SIZE:
        if start >= MAX_OFFSET:
            raise ValueError("bulletin pagination limit reached")
        parts = urlsplit(listing)
        query = urlencode({"startIndex": start + PAGE_SIZE, "maxResults": PAGE_SIZE})
        found.append(urlunsplit((parts.scheme, parts.netloc, parts.path, query, "")))
    return found
