"""Adapter for Files Gallery (files.gallery), a one-file PHP browser some communes serve their
documents through (Penthalaz: `/fichiers/`, recorded 2026-10-19).

The page holds no file anchors: a script assigns `const _c = {...}`, plain JSON with `query_path`
(the folder shown) and `dirs`, which maps folder paths to `{files: {name: {filetype: "dir" or
"file", url_path, mtime, ...}}}`. A folder's page is `<script dir>/?<url_path>`, a file is served at
`<script dir>/<url_path>`.

Two step selectors. `dirs` yields the subfolders of the folder shown, `files` its PDFs; the filters
see the folder or file name (and, for exclude_regex, the URL). With `also_documents` on a `dirs`
step, PDFs beside the subfolders are collected as well:

    listing_urls: ["https://www.penthalaz.ch/fichiers/?Conseil%20communal/PV%20du%20conseil"]
    adapter: files_gallery
    adapter_config:
      steps:
        - {selector: dirs, also_documents: true}
        - {selector: files, text_regex: Procès-verbal}

Dates come from the file name only ("2025-12-08 - Procès-verbal.pdf", the session); `mtime` is
when the file was uploaded and is never used.
"""

from __future__ import annotations

import json
import re
from urllib.parse import quote, urlsplit

from ...schemas import AdapterStep
from .base import Link, ListingAdapter, excluded
from .html_links import _first_date, clean_text

_MARKER = "const _c = "
_SAFE = "/()'!,;&=+$@"  # kept as written in url_path, as the gallery's own links keep them


def gallery(html: str) -> dict | None:
    """The `_c` object of a Files Gallery page, or None."""
    start = html.find(_MARKER)
    if start < 0:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(html, start + len(_MARKER))
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


class FilesGalleryAdapter(ListingAdapter):
    name = "files_gallery"

    def extract_links(
        self,
        html: str,
        base_url: str,
        step: AdapterStep,
        date_regex: str | None,
        date_order: str,
        parent: Link | None = None,
    ) -> list[Link]:
        data = gallery(html)
        if data is None:
            return []
        folder = (data.get("dirs") or {}).get(str(data.get("query_path") or ""))
        if not isinstance(folder, dict):
            return []
        parts = urlsplit(base_url)
        script_dir = f"{parts.scheme}://{parts.netloc}{parts.path.rsplit('/', 1)[0]}/"
        want_dirs = step.selector == "dirs"
        keep = re.compile(step.text_regex, re.IGNORECASE) if step.text_regex else None
        drop = re.compile(step.exclude_regex, re.IGNORECASE) if step.exclude_regex else None
        links: list[Link] = []
        for name, item in (folder.get("files") or {}).items():
            if not isinstance(item, dict) or name.startswith("."):
                continue
            is_dir = item.get("filetype") == "dir"
            path = str(item.get("url_path") or "")
            if is_dir != want_dirs or not path:
                continue
            if not is_dir and not name.lower().endswith(".pdf"):
                continue
            text = clean_text(re.sub(r"\.pdf$", "", name, flags=re.IGNORECASE))
            url = script_dir + ("?" if is_dir else "") + quote(path, safe=_SAFE)
            if keep and not keep.search(text):
                continue
            if excluded(drop, f"{text} {url}"):
                continue
            date = None if is_dir else _first_date([text], "", date_regex, date_order)
            links.append(Link(url=url, text=text, date=date))
        return links
