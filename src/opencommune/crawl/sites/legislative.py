"""Bounded public legislative API inventory with no inferred document metadata.

The API is advertised by the municipal legislative portal. Only listed legislatures,
paginated collection rows, and their typed PDF attachment endpoints are followed.
"""

from __future__ import annotations

import json
import re
from urllib.parse import parse_qsl, urlencode, urlsplit

KINDS = ("sessions", "messages", "motions", "interpellations", "questions")
PAGE_SIZE = 100
MAX_PAGE = 9999
MAX_LEGISLATURES = 30
MAX_DOCUMENTS_PER_RECORD = 100

_DOCUMENT_TAILS = {
    "sessions": (r"agenda", r"resolutionSummaries/[1-9]\d*", r"minutes/[1-9]\d*"),
    "messages": (r"messageText", r"attachments/[1-9]\d*", r"commissionReports/[1-9]\d*"),
    "motions": (
        r"motionText",
        r"preliminaryReport",
        r"admissibilityReport",
        r"attachments/[1-9]\d*",
        r"commissionReports/[1-9]\d*",
    ),
    "interpellations": (r"interpellationText", r"attachments/[1-9]\d*"),
    "questions": (r"questionText", r"municipalResponse", r"attachments/[1-9]\d*"),
}
_DOCUMENT_PATHS = {
    kind: re.compile(rf"/api/public/{kind}/[1-9]\d*/(?:{'|'.join(tails)})")
    for kind, tails in _DOCUMENT_TAILS.items()
}


def validate_origin(origin: str) -> str:
    parts = urlsplit(origin)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.port
        or parts.path not in {"", "/"}
        or parts.query
        or parts.fragment
    ):
        raise ValueError("legislative API origin must be a bare HTTPS host")
    return f"https://{parts.netloc}"


def collection_url(origin: str, kind: str, legislature_id: int, page: int) -> str:
    origin = validate_origin(origin)
    if kind not in KINDS or not _positive_int(legislature_id) or not _page_int(page):
        raise ValueError("invalid legislative collection request")
    query = urlencode({"legislationId": legislature_id, "page": page, "size": PAGE_SIZE})
    return f"{origin}/api/public/{kind}?{query}"


def _positive_int(value: object) -> bool:
    return type(value) is int and value > 0


def _page_int(value: object) -> bool:
    return type(value) is int and 0 <= value <= MAX_PAGE


def _request(url: str, origin: str) -> tuple[str, int | None, int | None] | None:
    origin = validate_origin(origin)
    parts = urlsplit(url)
    if parts.scheme + "://" + parts.netloc != origin or parts.fragment:
        return None
    if parts.path == "/api/public/legislations" and not parts.query:
        return "legislations", None, None
    kind = parts.path.removeprefix("/api/public/")
    if kind not in KINDS:
        return None
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    if len(pairs) != 3 or {key for key, _ in pairs} != {"legislationId", "page", "size"}:
        return None
    query = dict(pairs)
    if not all(re.fullmatch(r"\d+", query[key]) for key in query):
        return None
    legislature_id, page, size = (
        int(query["legislationId"]),
        int(query["page"]),
        int(query["size"]),
    )
    if legislature_id <= 0 or not _page_int(page) or size != PAGE_SIZE:
        return None
    return kind, legislature_id, page


def is_api_url(url: str, origin: str) -> bool:
    try:
        return _request(url, origin) is not None
    except (TypeError, ValueError):
        return False


def _document_url(endpoint: object, kind: str, origin: str) -> str | None:
    if not isinstance(endpoint, str):
        return None
    try:
        parts = urlsplit(endpoint)
    except ValueError:
        return None
    if parts.scheme or parts.netloc or parts.query or parts.fragment:
        return None
    if not _DOCUMENT_PATHS[kind].fullmatch(parts.path):
        return None
    return origin + parts.path


def links(payload: str, url: str, origin: str) -> tuple[list[str], list[str]]:
    """Return PDF attachment URLs and next scoped API pages from a validated response."""
    request = _request(url, origin)
    if request is None:
        raise ValueError("unreviewed legislative API route")
    origin = validate_origin(origin)
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError("invalid legislative JSON") from exc
    kind, legislature_id, page = request
    if kind == "legislations":
        if not isinstance(data, list) or not 1 <= len(data) <= MAX_LEGISLATURES:
            raise ValueError("legislatures must be a bounded nonempty list")
        ids = []
        for row in data:
            if not isinstance(row, dict) or not _positive_int(row.get("id")):
                raise ValueError("legislature ID must be positive")
            ids.append(row["id"])
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate legislature ID")
        return [], [
            collection_url(origin, item, legislature, 0) for legislature in ids for item in KINDS
        ]
    if not isinstance(data, dict):
        raise ValueError("collection page must be an object")
    rows = data.get("content")
    if not isinstance(rows, list) or len(rows) > PAGE_SIZE:
        raise ValueError("collection content must be a bounded list")
    number, size, total_pages, has_next = (
        data.get("pageNumber"),
        data.get("pageSize"),
        data.get("totalPages"),
        data.get("hasNext"),
    )
    if (
        number != page
        or type(number) is not int
        or size != PAGE_SIZE
        or type(size) is not int
        or type(total_pages) is not int
        or not 0 <= total_pages <= MAX_PAGE + 1
        or type(has_next) is not bool
        or (
            (page != 0 or rows or has_next)
            if total_pages == 0
            else (page >= total_pages or has_next != (page + 1 < total_pages))
        )
    ):
        raise ValueError("inconsistent legislative pagination")
    pdfs = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("documents"), list):
            raise ValueError("collection row needs a document list")
        documents = row["documents"]
        if len(documents) > MAX_DOCUMENTS_PER_RECORD:
            raise ValueError("too many documents in one record")
        for document in documents:
            if not isinstance(document, dict):
                continue
            filename = document.get("filename")
            if not isinstance(filename, str) or not filename.strip().lower().endswith(".pdf"):
                continue
            pdf = _document_url(document.get("endpoint"), kind, origin)
            if pdf:
                pdfs.append(pdf)
    children = [collection_url(origin, kind, legislature_id, page + 1)] if has_next else []
    return list(dict.fromkeys(pdfs)), children
