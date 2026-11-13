"""Bounded, title-agnostic navigation inside configured municipal sections."""

import re
from pathlib import PurePosixPath
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlsplit, urlunsplit

from .adapters.html_links import _base_href, unpack_embedded_tables
from .html_parse import parse_html
from .iweb import clean_url, same_site
from .sites.nextjs import link_tags as nextjs_links
from .sites.quicksite import legacy_page_urls, widget_urls
from .sites.sh_cms import file_node_urls as sh_file_node_urls

PAGE_BATCH = 20
MAX_PAGES = 2000
MAX_DEPTH = 6
# Long municipal news indexes can exceed 2 MB; keep a finite streaming bound.
MAX_HTML_BYTES = 4_000_000


def child_depth(parent, child, depth):
    """Pagination stays at the same navigation depth; total page limits still apply."""
    before, after = urlsplit(parent), urlsplit(child)
    if (before.scheme, before.netloc, before.path) != (after.scheme, after.netloc, after.path):
        return depth + 1
    left = dict(parse_qsl(before.query, keep_blank_values=True))
    right = dict(parse_qsl(after.query, keep_blank_values=True))
    changed = {k for k in left.keys() | right.keys() if left.get(k) != right.get(k)}
    # TYPO3's published pagination URLs may add/change a cache hash and a
    # fixed News controller. The URL remains intact; only depth accounting
    # ignores these metadata parameters when a numeric pager actually changes.
    typo3_pagers = {
        "tx_news_pi1[currentPage]",
        "tx_news_pi1[@widget_0][currentPage]",
        "tx_ttnews[pointer]",
    }
    if changed & typo3_pagers:
        if "cHash" in changed and re.fullmatch(r"[a-fA-F0-9]{32}", right.get("cHash", "")):
            changed.remove("cHash")
        controller = "tx_news_pi1[controller]"
        if controller in changed and controller not in left and right.get(controller) == "News":
            changed.remove(controller)
    if changed and all(
        (
            k in {"page", "start", "offset", "startIndex", "b_start"} | typo3_pagers
            or re.fullmatch(r"Page_[A-Za-z0-9_]+", k)
        )
        and re.fullmatch(r"[0-9]{1,6}", right.get(k, ""))
        for k in changed
    ):
        return depth
    return depth + 1


def within(url, prefix):
    """Path component boundaries, including query pagination on the section itself."""
    if not same_site(url, prefix):
        return False
    path = unquote(urlsplit(url).path)
    root = unquote(urlsplit(prefix).path).rstrip("/")
    if any(p in {".", ".."} for p in path.split("/")) or "\\" in path:
        return False
    # GOViS inserts a numeric routing ID after the section's .html slug.
    # Its child sections omit that routing segment; compare their logical paths.
    path = re.sub(r"\.html/\d+(?=/|$)", "", path)
    root = re.sub(r"\.html/\d+(?=/|$)", "", root)
    return path.rstrip("/") == root or path.startswith(root + "/")


def page_url(url):
    url = clean_url(url)
    if not url:
        return None
    parts = urlsplit(url)
    # Do not explore binary assets or links that trigger account/form actions.
    suffix = PurePosixPath(parts.path).suffix.lower()
    if suffix and suffix not in {".html", ".htm", ".php", ".aspx", ".asp", ".cfm"}:
        return None
    pairs = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in {"csrf", "csrf_token"}
    ]
    if any(k.lower() in {"logout", "delete", "sessionid", "phpsessid"} for k, _ in pairs):
        return None
    if any(
        k.lower() in {"cmd", "action", "apdo"}
        and v.lower() not in {"show", "detail", "list", "index"}
        for k, v in pairs
    ):
        return None
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(sorted(pairs)), ""))


def page_links(html, listing, source, document_urls):
    html = unpack_embedded_tables(html)
    if source.vendor == "sh-cms" and urlsplit(listing).path == "/CMS/content":
        return sorted(
            url
            for raw in sh_file_node_urls(html, listing)
            if (url := page_url(raw)) and source.allows_listing(url)
        )
    soup = parse_html(html)
    base = _base_href(soup, listing)
    found = set()
    documents = {clean_url(u) for u in document_urls}
    for a in [*soup.select("a[href]"), *nextjs_links(soup)]:
        try:
            raw = clean_url(urljoin(base, a["href"]))
            if raw in documents:
                continue
            url = page_url(raw) if raw else None
            if url and source.allows_listing(url):
                found.add(url)
        except ValueError:
            continue
    if "data-elasticsearch-" in html:
        for raw in widget_urls(html, listing):
            url = page_url(raw)
            if url and source.allows_listing(url):
                found.add(url)
    if "Quicksite" in html or "qsPortal" in html or "/qsportal/ajax/get.asp" in listing.lower():
        for raw in legacy_page_urls(html, listing):
            url = page_url(raw)
            if url and source.allows_listing(url):
                found.add(url)
    return sorted(found)
