"""Read public Wappler content fragments advertised by municipal page templates.

Only two observed read-only content endpoints are accepted. Their JSON carries HTML
in content_XX fields; scripts in those fragments are never executed.
"""

from __future__ import annotations

import html
import json
import re
from urllib.parse import parse_qs, urlsplit

_CONTENT_FIELD = re.compile(r"content_[0-9]{2}")
_SLUG = re.compile(r"[a-z0-9_-]{1,100}", re.I)


def is_content_url(url: str) -> bool:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.netloc or parts.fragment:
        return False
    query = parse_qs(parts.query, keep_blank_values=True)
    if parts.path == "/dmxConnect/api/gd_content.php":
        return (
            set(query) == {"url"}
            and len(query["url"]) == 1
            and bool(_SLUG.fullmatch(query["url"][0]))
        )
    if parts.path == "/dmxConnect/api/artcms_content.php":
        return (
            set(query) == {"menu_id"}
            and len(query["menu_id"]) == 1
            and bool(re.fullmatch(r"[1-9][0-9]{0,9}", query["menu_id"][0]))
        )
    return False


def html_document(payload: str, url: str, municipal_website: str) -> str:
    """Return only the endpoint's bounded content HTML with a municipal root base."""
    if not is_content_url(url):
        raise ValueError("not a configured Wappler content endpoint")
    try:
        node = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError("invalid Wappler JSON") from exc
    if not isinstance(node, dict):
        raise ValueError("Wappler response must be an object")
    if urlsplit(url).path.endswith("/gd_content.php"):
        record = node.get("query")
        if not isinstance(record, dict):
            raise ValueError("Wappler query must be an object")
        records = [record]
    else:
        records = node.get("content")
        if (
            not isinstance(records, list)
            or not 1 <= len(records) <= 10
            or any(not isinstance(record, dict) for record in records)
        ):
            raise ValueError("Wappler content must be a bounded object array")
    fragments = []
    for record in records:
        for key, value in record.items():
            if _CONTENT_FIELD.fullmatch(key) and value is not None:
                if not isinstance(value, str) or len(value) > 1_000_000:
                    raise ValueError("Wappler content field must be bounded HTML text")
                fragments.append(value)
    if not fragments or sum(map(len, fragments)) > 2_000_000:
        raise ValueError("Wappler response has no bounded content fragments")
    parts = urlsplit(municipal_website)
    root = f"{parts.scheme}://{parts.netloc}/"
    return '<base href="' + html.escape(root, quote=True) + '">' + "\n".join(fragments)
