"""Render public Arcantel pages through their published read-only WCF methods.

The human page remains the checkpoint and provenance URL. Only SharepointListe
paths explicitly declared in that page are followed, within configured sections.
"""

import json
from html import escape
from urllib.parse import urljoin, urlsplit

from .. import discovery, http
from ..html_parse import parse_html


def _json(client, polite, url, payload):
    if not polite.allowed(url):
        raise http.FetchFailure("robots", url, "disallowed by robots.txt")
    response = http._send(
        client, polite, client.build_request("POST", url, json=payload), stream=True
    )
    try:
        http._ensure_ok(response, url)
        data = bytearray()
        for chunk in response.iter_bytes(16384):
            data.extend(chunk)
            if len(data) > discovery.MAX_HTML_BYTES:
                raise http.FetchFailure(
                    "html_size", url, "Arcantel response exceeds discovery limit"
                )
        return json.loads(data)
    except (ValueError, RecursionError) as exc:
        raise http.FetchFailure("api_schema", url, "Invalid Arcantel JSON") from exc
    finally:
        response.close()


def render(client, polite, source, listing):
    """Fetch one declared page and its scoped public lists; fail on partial data."""
    if not source.allows_listing(listing):
        raise http.FetchFailure("external", listing, "Page outside configured sections")
    if not polite.allowed(listing):
        raise http.FetchFailure("robots", listing, "disallowed by robots.txt")
    page_path = urlsplit(listing).path
    page = _json(client, polite, urljoin(listing, "/Api/Page.svc/detail"), {"page": page_path})
    try:
        detail = page["DetailResult"]
        content = detail["Content"]
        if (
            not isinstance(content, str)
            or not isinstance(detail.get("Url"), str)
            or detail["Url"].rstrip("/") != page_path.rstrip("/")
        ):
            raise ValueError("Unexpected page identity or content")
    except (KeyError, TypeError, ValueError) as exc:
        raise http.FetchFailure("api_schema", listing, "Unexpected Arcantel page") from exc
    parts = [content]
    total = len(content.encode())
    paths = []
    for row in parse_html(content).select("tr"):
        cells = row.find_all(["td", "th"], recursive=False)
        if len(cells) >= 2 and cells[0].get_text(strip=True) == "SharepointListe":
            path = cells[1].get_text(strip=True)
            # No inferred IDs, cross-site paths, queries or arbitrary API calls.
            if not path.startswith("/") or path.startswith("//") or "?" in path or "#" in path:
                raise http.FetchFailure("api_schema", listing, "Invalid Arcantel list path")
            target = urljoin(listing, path)
            if not source.allows_listing(target):
                raise http.FetchFailure("external", target, "List outside configured sections")
            if target not in paths:
                paths.append(target)
    if len(paths) > 20:
        raise http.FetchFailure("html_size", listing, "Too many embedded Arcantel lists")
    for target in paths:
        if not polite.allowed(target):
            raise http.FetchFailure("robots", target, "disallowed by robots.txt")
        result = _json(
            client,
            polite,
            urljoin(listing, "/Api/List.svc/liste"),
            {"listeurl": urlsplit(target).path},
        )
        try:
            rows = result["ListeResult"]["Data"]["Data"]
            if not isinstance(rows, list):
                raise ValueError("Expected rows")
            for row in rows:
                if not isinstance(row, list):
                    raise ValueError("Expected fields")
                for field in row:
                    value = field["Value"]
                    if isinstance(value, str):
                        total += len(value.encode())
                        if total > discovery.MAX_HTML_BYTES:
                            raise http.FetchFailure(
                                "html_size", listing, "Rendered page exceeds discovery limit"
                            )
                        parts.append(value)
        except (KeyError, TypeError, ValueError) as exc:
            raise http.FetchFailure("api_schema", target, "Unexpected Arcantel list") from exc
    menu = _json(client, polite, urljoin(listing, "/Api/Menu.svc/children"), {"url": page_path})
    try:
        children = menu["ChildrenResult"]
        if not isinstance(children, list):
            raise ValueError("Expected menu entries")
        for child in children:
            path = child["FriendlyUrl"]
            if not isinstance(path, str):
                raise ValueError("Expected menu URL")
            target = urljoin(listing, path)
            if child.get("HideInMenu") is not True and source.allows_listing(target):
                link = '<a href="' + escape(target, quote=True) + '">Archive page</a>'
                total += len(link.encode())
                parts.append(link)
    except (KeyError, TypeError, ValueError) as exc:
        raise http.FetchFailure("api_schema", listing, "Unexpected Arcantel menu") from exc
    if total > discovery.MAX_HTML_BYTES:
        raise http.FetchFailure("html_size", listing, "Rendered page exceeds discovery limit")
    return "\n".join(parts)
