"""Read public Next.js hydration links as JSON, without executing JavaScript.

Only explicit URL fields in standard Next data are returned. The callers retain
normal municipal scope, robots, redirect, PDF validation and navigation limits.
"""

import json
import re
from contextlib import suppress

from bs4 import BeautifulSoup, Tag

_PUSH = re.compile(r"self\.__next_f\.push\(")
MAX_DATA_BYTES = 4_000_000
MAX_NODES = 100_000
MAX_LINKS = 4_000


def link_tags(soup: BeautifulSoup) -> list[Tag]:
    records = []
    chunks = []
    size = 0
    decoder = json.JSONDecoder()
    for script in soup.select("script:not([src])"):
        text = script.get_text()
        size += len(text)
        if size > MAX_DATA_BYTES:
            break
        if script.get("id") == "__NEXT_DATA__":
            with suppress(ValueError, RecursionError):
                records.append(json.loads(text))
        for match in _PUSH.finditer(text):
            try:
                value, end = decoder.raw_decode(text[match.end() :])
            except (ValueError, RecursionError):
                continue
            if not text[match.end() + end :].lstrip().startswith(")"):
                continue
            if (
                isinstance(value, list)
                and len(value) == 2
                and value[0] == 1
                and isinstance(value[1], str)
            ):
                chunks.append(value[1])
    # Flight rows may be split across script tags. Non-JSON control/text rows
    # are deliberately ignored rather than interpreted as executable code.
    for line in "".join(chunks).splitlines():
        key, separator, payload = line.partition(":")
        if separator and re.fullmatch(r"[0-9a-f]+", key):
            with suppress(ValueError, RecursionError):
                records.append(json.loads(payload))
    found = set()
    tags = []
    visited = 0
    while records and visited < MAX_NODES and len(tags) < MAX_LINKS:
        node = records.pop()
        visited += 1
        if isinstance(node, dict):
            for key, value in node.items():
                if key in {"href", "url", "src", "publicUrl"} and isinstance(value, str):
                    value = value.strip()
                    if value and value not in found:
                        found.add(value)
                        tag = soup.new_tag("a", href=value)
                        tags.append(tag)
                elif isinstance(value, (dict, list)):
                    records.append(value)
        elif isinstance(node, list):
            records.extend(reversed(node))
    return tags
