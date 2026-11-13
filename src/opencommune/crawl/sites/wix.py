"""Public PDF attachments embedded in Wix rich-content hydration data."""

import json
import re

from bs4 import BeautifulSoup

_FILE = re.compile(r"ugd/[0-9a-f]+_[0-9a-f]+\.pdf", re.I)


def document_urls(soup: BeautifulSoup) -> list[str]:
    """Read declared public FILE nodes, never private or arbitrary embedded URLs.

    Callers must still enforce the configured municipality's CDN tenant prefix,
    robots policy, response size and PDF bytes before storing any document.
    """
    script = soup.find("script", id="wix-warmup-data", type="application/json")
    if script is None:
        return []
    try:
        pending = [json.loads(script.get_text())]
    except (ValueError, RecursionError):
        return []
    found = set()
    while pending:
        node = pending.pop()
        if isinstance(node, list):
            pending.extend(node)
        elif isinstance(node, dict):
            data = node.get("fileData")
            if node.get("type") == "FILE" and isinstance(data, dict):
                src = data.get("src")
                if (
                    data.get("type") == "pdf"
                    and isinstance(src, dict)
                    and src.get("private") is False
                    and isinstance(src.get("id"), str)
                    and _FILE.fullmatch(src["id"])
                ):
                    found.add("https://static.wixstatic.com/" + src["id"])
            pending.extend(value for value in node.values() if isinstance(value, (dict, list)))
    return sorted(found)
