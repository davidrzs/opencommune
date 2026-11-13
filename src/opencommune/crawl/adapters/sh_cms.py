"""Adapter for the Schaffhausen cantonal CMS, the system the canton shares with communes such as
Hallau, Gächlingen, Rüdlingen and Bargen (marker: `/CMS/Webseite/...-<id>-DE.html` pages, scripts
under `/CMS/assets/`). The pages are rendered in the browser from JSON, but the same JSON is served
plainly: `GET /CMS/content?contentid=<id>&language=DE` answers one content node.

Two hops. The listing URL names the assembly article, whose `data_widget_data` holds one
`contentButtonAdder` field per assembly: a group title ("2. GV 2026 vom 16. Juni 2026"), the
buttons (content ids of file nodes, `contenttypeid` 101) and, optionally, custom labels ("6
Protokoll"). Step one (`selector: buttons`) yields the file nodes; the link text is the label and
the group title, the date the first one found in them. Step two (`selector: file`) reads a file
node: `data_filemeta.url` is the PDF under `/CMS/get/file/<uuid>`, `data_listlabel` or the original
file name the title; a date missing there comes from the previous hop, else from the node's
publication date. Filters apply to the text of each hop. Configuration:

    listing_urls: ["https://www.hallau.ch/CMS/content?contentid=4040278&language=DE"]
    adapter: sh_cms
    adapter_config:
      steps:
        - {selector: buttons, text_regex: Protokoll, max_follow: 8}
        - {selector: file, text_regex: Protokoll, kind: minutes}
      max_documents: 4

`listing_urls()` also accepts the page URL (`/CMS/Webseite/<site>/<title>-<id>-DE.html`) and turns
it into the JSON endpoint. No robots.txt on these hosts as of September 2026; the endpoint is a
plain GET without credentials.

Kiosk pages (Thayngen's Einwohnerrat, recorded 2026-10-19) have no button groups: a `kioskWidget`
lists the files of a repository folder, which the browser fetches from `GET /CMS/lists/list` with
Solr-style filters and receives as server-rendered HTML. That URL is the listing URL, kept as is:

    listing_urls: ["https://thayngen.ch/CMS/lists/list?filter_customposttypeid_int=101&filter_generic_filetype_string=(pdf%20OR%20PDF)&filter_published_string=published&filter_approvedpaths_string=*/<idpath of the folder>/*&filter_language_string=DE&sort=sortable_datetime%20desc&rows=200&start=0&mode=list"]
    adapter: sh_cms
    adapter_config:
      steps:
        - {selector: kiosk, text_regex: Protokoll}

Step `kiosk` reads each `.list_item_anchor`: its script holds the file metadata (`JSON.parse(...)`,
the PDF under `/CMS/get/file/<uuid>` and the original file name) and the title. The date is the one
in the title or file name only; the item's publication date is when the file was posted, not the
session's date, and is never used.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import Iterator
from urllib.parse import parse_qsl, urljoin, urlsplit

import httpx

from ...schemas import AdapterStep, SourceConfig
from ..html_parse import parse_html
from ..sites.sh_cms import button_groups
from .base import Link, ListingAdapter
from .html_links import _first_date, clean_text

FILE_TYPE = "101"  # contenttypeid of a file node
_PAGE_ID = re.compile(r"-(\d+)-([A-Z]{2})\.html$")
_DMY = re.compile(r"^(\d{2})\.(\d{2})\.(\d{4})")
_LIST_PATH = "/CMS/lists/list"
_KIOSK_META = re.compile(r"JSON\.parse\('(.*?)'\);", re.S)
_KIOSK_TITLE = re.compile(r"var title = PS\.Helper\.replaceBR\('(.*?)'\);", re.S)
_JS_ESCAPE = re.compile(r"\\(u[0-9a-fA-F]{4}|.)", re.S)


def node_url(url: str) -> str:
    """The JSON endpoint of the node a page URL or an endpoint URL names."""
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    query = dict(parse_qsl(parts.query))
    if "contentid" in query:
        return f"{origin}/CMS/content?contentid={query['contentid']}&language={query.get('language', 'DE')}"
    m = _PAGE_ID.search(parts.path)
    if not m:
        raise ValueError(f"not a Schaffhausen CMS page or node URL: {url}")
    return f"{origin}/CMS/content?contentid={m[1]}&language={m[2]}"


def _js_string(value: str) -> str:
    """The text of a single-quoted JavaScript string literal's body."""

    def unescape(m: re.Match[str]) -> str:
        code = m[1]
        if code[0] == "u" and len(code) == 5:
            return chr(int(code[1:], 16))
        return {"n": "\n", "t": "\t", "r": "\r"}.get(code, code)

    return _JS_ESCAPE.sub(unescape, value)


def _widgets(data: dict) -> Iterator[dict]:
    raw = data.get("data_widget_data")
    try:
        tree = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return
    yield from button_groups(tree)


_DAY_MONTH = re.compile(r"\b(\d{1,2}\.\s*[A-Za-zÄÖÜäöüéû]{3,})(?!\s*\d)")
_YEAR = re.compile(r"\b((?:19|20)\d\d)\b")


def _group_date(title: str, date_regex: str | None, order: str) -> dt.date | None:
    """The assembly date in a group title. "2. GV 2026 vom 16. Juni 2026" parses as is; in
    "1. GV 2023 vom 13. April" the year stands before the day and month and is joined to them."""
    date = _first_date([title], "", date_regex, order)
    if date is not None:
        return date
    day_month, year = _DAY_MONTH.search(title), _YEAR.search(title)
    if day_month and year:
        return _first_date([f"{day_month[1]} {year[1]}"], "", date_regex, order)
    return None


def _publication_date(data: dict) -> dt.date | None:
    m = _DMY.match(str(data.get("data_publication_date") or ""))
    if not m:
        return None
    try:
        return dt.date(int(m[3]), int(m[2]), int(m[1]))
    except ValueError:
        return None


class ShCmsAdapter(ListingAdapter):
    name = "sh_cms"

    def listing_urls(self, source: SourceConfig) -> list[str]:
        return [u if urlsplit(u).path == _LIST_PATH else node_url(u) for u in source.listing_urls]

    def request(self, step: AdapterStep, url: str) -> httpx.Request:
        if urlsplit(url).path == _LIST_PATH:  # the kiosk list answers HTML
            return httpx.Request("GET", url)
        return httpx.Request("GET", url, headers={"Accept": "application/json"})

    def extract_links(
        self,
        html: str,
        base_url: str,
        step: AdapterStep,
        date_regex: str | None,
        date_order: str,
        parent: Link | None = None,
    ) -> list[Link]:
        if step.selector == "kiosk":
            return self._kiosk_links(html, base_url, step, date_regex, date_order)
        try:
            data = json.loads(html)
        except ValueError:
            return []
        if not isinstance(data, dict):
            return []
        keep = re.compile(step.text_regex, re.IGNORECASE) if step.text_regex else None
        drop = re.compile(step.exclude_regex, re.IGNORECASE) if step.exclude_regex else None
        if step.selector == "file":
            link = self._file_link(data, base_url, date_regex, date_order, parent)
            if link is None:
                return []
            # the filters see the file's title and the button label that led here: a label
            # "Protokoll GV Nr. 116" may point at a file named only "GV Nr. 116"
            subject = link.text + " " + (parent.text if parent else "")
            if keep and not keep.search(subject):
                return []
            if drop and drop.search(subject + " " + link.url):
                return []
            return [link]
        return self._button_links(data, base_url, step, keep, drop, date_regex, date_order)

    def _button_links(
        self, data: dict, base_url: str, step: AdapterStep, keep, drop, date_regex, date_order
    ) -> list[Link]:
        parts = urlsplit(base_url)
        origin = f"{parts.scheme}://{parts.netloc}"
        language = dict(parse_qsl(parts.query)).get("language", "DE")
        url_re = re.compile(step.url_regex, re.IGNORECASE) if step.url_regex else None
        links: list[Link] = []
        seen: set[str] = set()
        for group in _widgets(data):
            title = clean_text(str(group.get("title") or ""))
            labels = {
                str(c.get("contentid")): clean_text(str(c.get("label") or ""))
                for c in group.get("customLabels") or []
                if isinstance(c, dict)
            }
            group_date = _group_date(title, date_regex, date_order)
            # the labelled ids first: a group can label live file nodes while its `buttons`
            # still list ids of deleted ones (Rüdlingen), and the site renders the labelled set
            ids = [cid for cid in labels if cid and cid != "None"]
            ids += [
                str(b.get("contentid") or "")
                for b in group.get("buttons") or []
                if isinstance(b, dict) and str(b.get("contenttypeid")) == FILE_TYPE
            ]
            for cid in ids:
                if not cid or cid in seen:
                    continue
                label = labels.get(cid, "")
                text = f"{label} ({title})" if label and title else label or title
                if keep and not keep.search(text):
                    continue
                if drop and drop.search(text):
                    continue
                url = f"{origin}/CMS/content?contentid={cid}&language={language}"
                if url_re and not url_re.search(url):
                    continue
                seen.add(cid)
                date = _first_date([label], "", date_regex, date_order) if label else None
                links.append(
                    Link(
                        url=url,
                        text=text,
                        date=date or group_date,
                        context_date=group_date if date is None else None,
                        upstream_id=cid,
                    )
                )
        return links

    def _kiosk_links(
        self, html: str, base_url: str, step: AdapterStep, date_regex, date_order
    ) -> list[Link]:
        keep = re.compile(step.text_regex, re.IGNORECASE) if step.text_regex else None
        drop = re.compile(step.exclude_regex, re.IGNORECASE) if step.exclude_regex else None
        links: list[Link] = []
        seen: set[str] = set()
        for item in parse_html(html).select(".list_item_anchor"):
            script = " ".join(s.get_text() for s in item.find_all("script"))
            meta_m, title_m = _KIOSK_META.search(script), _KIOSK_TITLE.search(script)
            if not meta_m:
                continue
            try:
                meta = json.loads(_js_string(meta_m[1]))
            except ValueError:
                continue
            original = str(meta.get("originalname") or "")
            if not meta.get("url") or not original.lower().endswith(".pdf"):
                continue
            title = clean_text(_js_string(title_m[1]) if title_m else original)
            title = re.sub(r"\.pdf$", "", title, flags=re.IGNORECASE)
            url = urljoin(base_url, str(meta["url"]))
            if url in seen or (keep and not keep.search(title)):
                continue
            if drop and drop.search(f"{title} {original} {url}"):
                continue
            seen.add(url)
            anchor = item.select_one("[contentid]")
            links.append(
                Link(
                    url=url,
                    text=title,
                    date=_first_date([title, original], "", date_regex, date_order),
                    upstream_id=anchor.get("contentid") if anchor else None,
                )
            )
        return links

    def _file_link(
        self, data: dict, base_url: str, date_regex, date_order, parent: Link | None
    ) -> Link | None:
        raw = data.get("data_filemeta")
        try:
            meta = json.loads(raw) if isinstance(raw, str) else raw
        except ValueError:
            return None
        if not isinstance(meta, dict) or not meta.get("url"):
            return None
        original = str(meta.get("originalname") or "")
        if str(data.get("data_filetype") or "").lower() != "pdf" and not original.lower().endswith(
            ".pdf"
        ):
            return None
        title = clean_text(
            str(data.get("data_listlabel") or data.get("data_file_name") or original)
        )
        date = _first_date([title, original], "", date_regex, date_order)
        context = None
        if date is None and parent is not None and parent.date is not None:
            date, context = parent.date, parent.date
        if date is None:
            date = _publication_date(data)
        return Link(
            url=urljoin(base_url, str(meta["url"])),
            text=title,
            date=date,
            context_date=context,
            upstream_id=str(data.get("contentid") or "") or None,
        )
