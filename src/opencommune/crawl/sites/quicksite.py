"""Extract scoped Quicksite document searches and their attributed file nodes.

These functions only interpret HTML already retrieved by the caller. They do not
guess a site's project name, issue requests, or expand a scoped document widget
into a site-wide search.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

_SCRIPT = re.compile(
    r"^/coreapi/elasticsearch/projects/([A-Za-z0-9_-]+)/assets/js/elasticsearch\.js$"
)
_DOCUMENT_VIEWS = {"document", "cards", "documentconseil", "documentconseildates"}
_SEARCH = re.compile(
    r"^/coreapi/elasticsearch/projects/[A-Za-z0-9_-]+/"
    r"(document|cards|documentconseil|documentconseildates)/search$"
)
_FILE_NODE = re.compile(r"^/n([1-9][0-9]*)/?$")
_LEGACY_FILE = re.compile(r"^/N[1-9][0-9]+/[^/]+\.html$")
_QUICKSITE_FINGERPRINT = re.compile(r"/(?:coreapi/elasticsearch/projects/|qsportal/)", re.I)


def _origin(url: str) -> str | None:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.netloc or parts.username:
        return None
    return f"{parts.scheme}://{parts.netloc}"


def _same_host(url: str, listing: str) -> bool:
    target, source = urlsplit(url), urlsplit(listing)
    return (
        target.scheme in {"http", "https"}
        and target.netloc.lower() == source.netloc.lower()
        and not target.username
        and not target.password
    )


def _camelcase(name: str) -> str:
    first, *rest = name.split("-")
    return first + "".join(part[:1].upper() + part[1:] for part in rest)


def _observed_project(soup: BeautifulSoup, listing: str) -> str | None:
    projects = set()
    for script in soup.select("script[src]"):
        raw = script.get("src", "")
        match = _SCRIPT.fullmatch(urlsplit(raw).path)
        if match and _same_host(urljoin(listing, raw), listing):
            projects.add(match[1])
    return projects.pop() if len(projects) == 1 else None


def _older_quicksite(soup: BeautifulSoup) -> bool:
    generator = soup.find("meta", attrs={"name": re.compile(r"^generator$", re.I)})
    return bool(
        generator
        and "quicksite" in generator.get("content", "").lower()
        and soup.select('script[src^="/qsPortal/"]')
    )


def _lazy_ajax_node(listing: str, soup: BeautifulSoup) -> tuple[int, int] | None:
    parts = urlsplit(listing)
    if parts.path.lower() != "/qsportal/ajax/get.asp":
        return None
    query = parse_qs(parts.query)
    if query.get("Ajax") != ["getnode"] or query.get("NoLimitPage") != ["1"]:
        return None
    node, page = query.get("N", [""])[0], query.get("page", [""])[0]
    if not (node.isascii() and node.isdecimal() and page.isascii() and page.isdecimal()):
        return None
    if int(node) <= 0 or not 2 <= int(page) <= 100:
        return None
    if soup.select_one(f".tplSearchDocuments#a{node}") is None:
        return None
    return int(node), int(page)


def widget_urls(html: str, listing: str) -> list[str]:
    """Build search URLs only for observed, scoped Quicksite document widgets.

    The public Quicksite script derives ``<view>/search`` from its own project
    path, then submits ``q`` and the widget's camel-cased ``data-*`` attributes.
    A document widget needs a positive node or parent-node scope; otherwise a
    blank query would search the whole municipal site.
    """
    if "/coreapi/elasticsearch/projects/" not in html:
        return []
    origin = _origin(listing)
    if origin is None:
        return []
    soup = BeautifulSoup(html, "html.parser")
    project = _observed_project(soup, listing)
    if project is None:
        return []
    found = []
    for widget in soup.select("[data-elasticsearch-project][data-elasticsearch-view]"):
        view = widget.get("data-elasticsearch-view")
        if view not in _DOCUMENT_VIEWS:
            continue
        attrs = {
            key: str(value)
            for key, value in widget.attrs.items()
            if key.startswith("data-elasticsearch-") and isinstance(value, str)
        }
        scopes = [attrs.get("data-elasticsearch-node"), attrs.get("data-elasticsearch-parentnode")]
        if not any(
            value and value.isascii() and value.isdecimal() and int(value) > 0 for value in scopes
        ):
            continue
        if any(value and (not value.isascii() or not value.isdecimal()) for value in scopes):
            continue
        endpoint = f"{origin}/coreapi/elasticsearch/projects/{project}/{view}/search"
        query = [("q", "")]
        query.extend((_camelcase(key.removeprefix("data-")), value) for key, value in attrs.items())
        url = endpoint + "?" + urlencode(query)
        if url not in found:
            found.append(url)
    return found


def legacy_document_urls(html: str, listing: str) -> list[str]:
    """Candidate file nodes from configured Quicksite document containers.

    Four observed municipal templates put direct PDF nodes behind ``/N...html``
    links. Their links open in a new tab inside a document-list section or article,
    while menus outside ``main`` contain ordinary navigation to the same URL shape.
    This markup is evidence of a document *candidate*, not proof of PDF content;
    the caller must check robots, response MIME and PDF magic after redirect.
    """
    if not _QUICKSITE_FINGERPRINT.search(html) and not _QUICKSITE_FINGERPRINT.search(listing):
        return []
    if _origin(listing) is None:
        return []
    soup = BeautifulSoup(html, "html.parser")
    project = _observed_project(soup, listing)
    older = _older_quicksite(soup)
    ajax = _lazy_ajax_node(listing, soup)
    if project is None and not older and ajax is None:
        return []
    found = []
    for anchor in soup.select('main a[target="_blank"][href]') if project else []:
        if anchor.find_parent("nav"):
            continue
        container = anchor.find_parent("article") or anchor.find_parent(
            "section", class_=["tplListDocuments", "tplDphChildsIcons"]
        )
        if container is None:
            continue
        url = urljoin(listing, anchor["href"])
        if not _same_host(url, listing):
            continue
        parts = urlsplit(url)
        if not _LEGACY_FILE.fullmatch(parts.path) or parts.query or parts.fragment:
            continue
        if url not in found:
            found.append(url)
    # Older Quicksite pages render document cards on the server, outside <main>.
    # Etagnières uses a dedicated download icon inside each tplDocumentItem.
    for card in soup.select(".tplDocumentItem"):
        if not (older or ajax) or not re.search(r"\bpdf\b", card.get_text(" ", strip=True), re.I):
            continue
        for anchor in card.select('a.icon-download[target="_blank"][href]'):
            url = urljoin(listing, anchor["href"])
            parts = urlsplit(url)
            if (
                _same_host(url, listing)
                and _LEGACY_FILE.fullmatch(parts.path)
                and not parts.query
                and not parts.fragment
                and url not in found
            ):
                found.append(url)
    # Older Bootstrap templates use a download icon inside the link itself.
    # These may be HTML-looking /N... routes whose response is a PDF.
    for anchor in (
        soup.select(".tplSearchDocuments a[href], .tplDphChildsLinks a[href]") if older else []
    ):
        if anchor.select_one(".glyphicon-download") is None:
            continue
        url = urljoin(listing, anchor["href"])
        parts = urlsplit(url)
        if (
            _same_host(url, listing)
            and _LEGACY_FILE.fullmatch(parts.path)
            and not parts.query
            and not parts.fragment
            and url not in found
        ):
            found.append(url)
    # Aigle's summary cards pair a numeric detail node with an explicit PDF
    # download handler for that same node. Keep the download URL, not the detail.
    for card in soup.select(".tplDocumentSummaryItem") if project else []:
        if not re.search(r"\bpdf\b", card.get_text(" ", strip=True), re.I):
            continue
        detail_ids = {
            m[1]
            for anchor in card.select('a[title="Voir le détail"][href]')
            if (m := re.fullmatch(r"/N([1-9][0-9]+)/[^/]+\.html", urlsplit(anchor["href"]).path))
        }
        for anchor in card.select('a[title="Télécharger le document"][href]'):
            url = urljoin(listing, anchor["href"])
            parts = urlsplit(url)
            query = parse_qs(parts.query)
            if (
                _same_host(url, listing)
                and parts.path.lower() == "/qsportal/home.asp"
                and query.get("DocAction") == ["Download"]
                and len(query.get("N", [])) == 1
                and query["N"][0] in detail_ids
                and url not in found
            ):
                found.append(url)
    return found


def legacy_page_urls(html: str, listing: str) -> list[str]:
    """Observed older Quicksite pagination, without guessing an unscoped search.

    Aigle renders ``#p2`` links for a form's ``Page_0`` query parameter.
    Etagnières' public load-more script requests the current node via
    ``qsPortal/Ajax/get.asp``. Its page fragment can lead to the next page while
    it still contains document items and the load-more control.
    """
    if not _QUICKSITE_FINGERPRINT.search(html) and not _QUICKSITE_FINGERPRINT.search(listing):
        return []
    origin = _origin(listing)
    if origin is None:
        return []
    soup = BeautifulSoup(html, "html.parser")
    found = []
    if _observed_project(soup, listing) or _older_quicksite(soup):
        for pagination in soup.select(".pagination[data-parampagename][data-formname]"):
            name = pagination.get("data-parampagename", "")
            form = soup.find("form", attrs={"name": pagination.get("data-formname", "")})
            if not re.fullmatch(r"Page_[a-zA-Z0-9_]+", name) or form is None:
                continue
            if form.get("method", "get").lower() != "get" or form.get("action", ""):
                continue
            if form.find("input", attrs={"name": name}) is None:
                continue
            parts = urlsplit(listing)
            for anchor in pagination.select('a[href^="#p"]'):
                match = re.fullmatch(r"#p([1-9][0-9]*)", anchor["href"])
                if not match or int(match[1]) > 200:
                    continue
                query = [(key, value) for key, value in parse_qsl(parts.query) if key != name]
                query.append((name, match[1]))
                url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))
                if url != listing and url not in found:
                    found.append(url)
    node_page = _lazy_ajax_node(listing, soup)
    if node_page is not None:
        _, page = node_page
        if page < 100 and soup.select(".tplDocumentItem") and soup.select(".lazy-button"):
            parts = urlsplit(listing)
            query = [(key, value) for key, value in parse_qsl(parts.query) if key != "page"]
            query.append(("page", str(page + 1)))
            found.append(urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), "")))
    elif _older_quicksite(soup) and soup.select(".tplDocumentItem") and soup.select(".lazy-button"):
        # Derive only the current node explicitly assigned by this page.
        match = re.search(r"gobjSessionVar\.lngCurrentNodeFK\s*=\s*([1-9][0-9]*)\s*;", html)
        if match and soup.select_one(f".tplSearchDocuments#a{match[1]}"):
            found.append(
                f"{origin}/qsPortal/Ajax/get.asp?Ajax=getnode&NoLimitPage=1&N={match[1]}&page=2"
            )
    return found


def document_urls(html: str, listing: str) -> list[str]:
    """Return only /n<ID> links whose ID matches the enclosing result card."""
    if _origin(listing) is None or not _SEARCH.fullmatch(urlsplit(listing).path):
        return []
    soup = BeautifulSoup(html, "html.parser")
    found = []
    for card in soup.select("[data-qsedit-editnode]"):
        # Quicksite uses the same /n<ID> route for archive folders and files.
        # Index cards must remain HTML navigation for scoped discovery to follow.
        if "qs-edit-index" in card.get("class", []):
            continue
        node_id = card.get("data-qsedit-editnode", "")
        if not node_id.isascii() or not node_id.isdecimal() or int(node_id) <= 0:
            continue
        for anchor in card.select("a[href]"):
            # Nested cards, if any, own their links rather than their parent.
            if anchor.find_parent(attrs={"data-qsedit-editnode": True}) is not card:
                continue
            url = urljoin(listing, anchor["href"])
            if not _same_host(url, listing):
                continue
            parts = urlsplit(url)
            match = _FILE_NODE.fullmatch(parts.path)
            if not match or match[1] != node_id or parts.query or parts.fragment:
                continue
            clean = f"{parts.scheme}://{parts.netloc}/n{node_id}"
            if clean not in found:
                found.append(clean)
    return found
