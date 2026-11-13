"""Public Schaffhausen CMS document groups for the broad linked archive.

The configured ``/CMS/content`` nodes expose document-button groups as JSON. Each
button names another content node; that node's file metadata names the PDF.
These functions only follow those two explicit relationships and make no HTTP
requests or site-wide CMS searches.
"""

from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urljoin, urlsplit

_FILE_PATH = re.compile(r"/CMS/get/file/[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")


def validate_node(payload: str, listing: str) -> dict:
    """Validate that a CMS JSON response belongs to the requested public node."""
    parts = urlsplit(listing)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.netloc
        or parts.username
        or parts.password
        or parts.fragment
        or parts.path != "/CMS/content"
    ):
        raise ValueError("not a public Schaffhausen CMS content node")
    query = parse_qs(parts.query)
    if not set(query) <= {"contentid", "language"}:
        raise ValueError("unexpected CMS content query parameter")
    ids = query.get("contentid", [])
    if len(ids) != 1 or not ids[0].isascii() or not ids[0].isdecimal() or int(ids[0]) <= 0:
        raise ValueError("invalid CMS content ID")
    if query.get("language") not in (None, ["DE"]):
        raise ValueError("unexpected CMS content language")
    try:
        node = json.loads(payload)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid CMS content JSON") from exc
    if not isinstance(node, dict) or str(node.get("contentid")) != ids[0]:
        raise ValueError("CMS response content ID does not match request")
    return node


def _node(payload: str, listing: str) -> dict | None:
    try:
        return validate_node(payload, listing)
    except ValueError:
        return None


def button_groups(item):
    """The document-button groups in a widget tree, depth first in document order (the page shows
    them top to bottom)."""
    if isinstance(item, dict):
        if item.get("type") == "contentButtonAdder" and isinstance(item.get("data"), dict):
            yield item["data"]
        for value in item.values():
            yield from button_groups(value)
    elif isinstance(item, list):
        for value in item:
            yield from button_groups(value)


def _download_lists(item):
    """Explicit download IDs in a published CMS category's list widget."""
    if isinstance(item, dict):
        if item.get("type") == "contentListGenerator" and isinstance(item.get("data"), dict):
            for group in item["data"].get("contenttypes") or []:
                if (
                    isinstance(group, dict)
                    and group.get("key") == "downloads"
                    and group.get("visible") is True
                ):
                    hidden = {str(value) for value in group.get("unvisibleIds") or []}
                    for value in group.get("contentids") or []:
                        if str(value) not in hidden:
                            yield value
        for value in item.values():
            yield from _download_lists(value)
    elif isinstance(item, list):
        for value in item:
            yield from _download_lists(value)


def file_node_urls(payload: str, listing: str) -> list[str]:
    """Return explicit file or download-category nodes from a configured CMS widget."""
    node = _node(payload, listing)
    if node is None:
        return []
    # Older public section nodes can omit this field; explicit draft/private
    # parents are excluded, while PDF file nodes are strictly checked below.
    if node.get("data_published") not in (None, "", "published"):
        return []
    raw = node.get("data_widget_data")
    try:
        widgets = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError as exc:
        raise ValueError("invalid CMS widget JSON") from exc
    if not isinstance(widgets, (dict, list)):
        return []
    origin = f"{urlsplit(listing).scheme}://{urlsplit(listing).netloc}"
    language = parse_qs(urlsplit(listing).query).get("language", ["DE"])[0]
    found: list[str] = []
    for group in button_groups(widgets):
        ids = [
            entry.get("contentid")
            for entry in group.get("customLabels") or []
            if isinstance(entry, dict)
        ]
        ids.extend(
            entry.get("contentid")
            for entry in group.get("buttons") or []
            if isinstance(entry, dict) and str(entry.get("contenttypeid")) in {"101", "402"}
        )
        for value in ids:
            number = str(value or "")
            if not number.isascii() or not number.isdecimal() or int(number) <= 0:
                continue
            url = f"{origin}/CMS/content?contentid={number}&language={language}"
            if url not in found:
                found.append(url)
    if str(node.get("contenttypeid")) == "402":
        for value in _download_lists(widgets):
            number = str(value or "")
            if not number.isascii() or not number.isdecimal() or int(number) <= 0:
                continue
            url = f"{origin}/CMS/content?contentid={number}&language={language}"
            if url not in found:
                found.append(url)
    return found


def document_urls(payload: str, listing: str) -> list[str]:
    """Return an attributed PDF URL from a matching public file-node response."""
    node = _node(payload, listing)
    if node is None or str(node.get("contenttypeid")) != "101":
        return []
    if node.get("data_published") != "published":
        return []
    original_type = str(node.get("data_filetype") or "").lower()
    raw = node.get("data_filemeta")
    try:
        meta = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError as exc:
        raise ValueError("invalid CMS file metadata JSON") from exc
    if not isinstance(meta, dict) or not isinstance(meta.get("url"), str):
        if original_type == "pdf":
            raise ValueError("published CMS PDF node lacks file URL metadata")
        return []
    original = str(meta.get("originalname") or "")
    if original_type != "pdf" and not original.lower().endswith(".pdf"):
        return []
    target = urljoin(listing, meta["url"])
    parts, source = urlsplit(target), urlsplit(listing)
    if (
        parts.scheme != source.scheme
        or parts.netloc.lower() != source.netloc.lower()
        or parts.username
        or parts.password
        or not _FILE_PATH.fullmatch(parts.path)
        or parts.query
        or parts.fragment
    ):
        return []
    return [target]
