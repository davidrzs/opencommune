"""Raw document store: the URL index (data/raw/urls.jsonl) and writes into data/raw.

Known URLs are never re-downloaded (a known decision page is asked for again, conditionally, and
stored only when its decisions changed).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import os
import threading
from collections.abc import Iterable
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from ..config import settings
from ..schemas import AdapterStep, CommuneConfig, DocumentLink, RawSidecar
from . import html_document, http, storage

log = logging.getLogger(__name__)

INDEX_FILE = "urls.jsonl"  # append-only, one line per fetched URL; keyed in memory by canonical URL
VOLATILE_PARAMS = frozenset({"tmstv", "panntime", "pannorg", "rif", "timestamp", "_ts", "nocache"})
MAX_PDF_BYTES = 200 * 1024 * 1024
MAX_HTML_BYTES = 5 * 1024 * 1024
# a stored document is <sha>.pdf or, for a decision page, <sha>.html
RAW_SUFFIXES = (".pdf", ".html")
CHUNK_BYTES = 64 * 1024


# --- URL index ------------------------------------------------------------------


def canonical_url(url: str, volatile: Iterable[str] = ()) -> str:
    """The URL without its fragment and without volatile query parameters (cache busters, session
    stamps): the key under which a fetched document is remembered. Other parameters keep their order."""
    parts = urlsplit(url)
    drop = VOLATILE_PARAMS.union(name.lower() for name in volatile)
    query = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() not in drop
    ]
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path, urlencode(query), "")
    )


def index_path() -> Path:
    return settings.raw_dir / INDEX_FILE


def load_index() -> dict[str, dict]:
    """canonical_url -> newest entry (url, canonical_url, sha256, etag, last_modified, fetched_at,
    commune_bfs_id, adapter), with `communes`: every commune that linked the URL."""
    path = index_path()
    if not path.exists():
        return {}
    index: dict[str, dict] = {}
    with path.open(encoding="utf-8") as lines:
        for n, line in enumerate(lines, 1):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except ValueError:  # a line cut short by a crash
                log.warning("%s line %d is not JSON and was skipped", path, n)
                continue
            _remember(index, entry)
    return index


def _communes(entry: dict) -> list[int]:
    return entry.get("communes") or [entry.get("commune_bfs_id")]


def _remember(index: dict[str, dict], entry: dict) -> None:
    """The newest entry per URL, carrying every commune seen for it."""
    prior = index.get(entry["canonical_url"])
    communes = {*(_communes(prior) if prior else ()), entry["commune_bfs_id"]}
    index[entry["canonical_url"]] = {**entry, "communes": sorted(communes)}


def rebuild_index(volatile: dict[int, Iterable[str]] | None = None) -> dict[str, dict]:
    """Rewrite urls.jsonl from the sidecars in data/raw and return the loaded index. `volatile` gives
    the extra volatile parameters per commune. URLs known only as duplicates of a held file are lost."""
    settings.raw_dir.mkdir(parents=True, exist_ok=True)
    entries: list[dict] = []
    for p in sorted(settings.raw_dir.glob("*.json")):
        try:
            sc = RawSidecar.model_validate_json(p.read_text(encoding="utf-8"))
        except ValueError:
            log.warning("%s is not a sidecar and was skipped", p)
            continue
        key = canonical_url(sc.source_url, (volatile or {}).get(sc.commune_bfs_id, ()))
        headers = {"etag": sc.etag, "last-modified": sc.last_modified}
        entries.append(
            _index_entry(
                sc.source_url,
                key,
                sc.sha256,
                headers,
                sc.fetched_at,
                sc.commune_bfs_id,
                sc.adapter,
                sc.content_sha256,
            )
        )
    entries.sort(key=lambda e: e["fetched_at"])
    _write_index(index_path(), entries)
    return load_index()


def _index_entry(
    url,
    key,
    sha,
    headers,
    fetched_at: dt.datetime,
    bfs_id: int,
    adapter: str | None,
    content_sha256: str | None = None,
) -> dict:
    entry = {
        "url": url,
        "canonical_url": key,
        "sha256": sha,
        "etag": headers.get("etag"),
        "last_modified": headers.get("last-modified"),
        "fetched_at": fetched_at.isoformat(),
        "commune_bfs_id": bfs_id,
        "adapter": adapter,
    }
    if content_sha256 is not None:  # decision pages only, see _download_page_locked
        entry["content_sha256"] = content_sha256
    return entry


def held(sha: str) -> bool:
    """Whether data/raw holds the document <sha>, as a PDF or as a decision page."""
    return any((settings.raw_dir / f"{sha}{suffix}").exists() for suffix in RAW_SUFFIXES)


def _write_index(path: Path, entries: list[dict]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def _index_add(index: dict[str, dict], entry: dict) -> None:
    """Append one entry to urls.jsonl and to the loaded index."""
    with index_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    _remember(index, entry)


# Bounded locks prevent duplicate URL streams and serialize hash/sidecar/index publication.
_DOWNLOAD_LOCKS = [threading.Lock() for _ in range(256)]
_PUBLISH_LOCK = threading.Lock()


def _download(link, commune, client, polite, index, volatile=(), step: AdapterStep | None = None):
    """`step` is the source's last step: with `capture: html` the link is a decision page."""
    key = canonical_url(link.url, volatile)
    stripe = int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) % len(_DOWNLOAD_LOCKS)
    with _DOWNLOAD_LOCKS[stripe]:
        if step is not None and step.capture == "html":
            return _download_page_locked(
                link, commune, client, polite, index, volatile, step.content_selector
            )
        return _download_locked(link, commune, client, polite, index, volatile)


def _download_locked(
    link: DocumentLink,
    commune: CommuneConfig,
    client: httpx.Client,
    polite: http.Politeness,
    index: dict[str, dict],
    volatile: Iterable[str] = (),
) -> str | None:
    """Fetch one document into data/raw unless its canonical URL is known. Returns the sha256 of a
    new file, None for a known document or a duplicate of a held file. Raises FetchFailure (robots,
    http, timeout, not_pdf, too_large).

    The body is streamed to a .part file while it is hashed; the sidecar is written before the part
    is renamed to <sha>.pdf, so a PDF without a sidecar never exists on disk."""
    key = canonical_url(link.url, volatile)
    known = index.get(key)
    if known and held(known["sha256"]):
        if commune is not None and commune.bfs_id not in _communes(known):
            # Another commune links the same file: one file can belong to several communes
            # (David, 2026-11-13). Recorded in the index; nothing is downloaded.
            headers = {"etag": known.get("etag"), "last-modified": known.get("last_modified")}
            now = dt.datetime.now(dt.UTC)
            entry = _index_entry(
                link.url, key, known["sha256"], headers, now, commune.bfs_id, link.adapter
            )
            with _PUBLISH_LOCK:
                _index_add(index, entry)
        return None  # never re-download a known document
    storage.require_space(MAX_PDF_BYTES)
    r, fetched_url = _open_document(link, client, polite)
    try:
        sha, size, part = _stream_to_part(r, fetched_url)
    finally:
        r.close()
    pdf_path = settings.raw_dir / f"{sha}.pdf"
    fetched_at = dt.datetime.now(dt.UTC)
    entry = _index_entry(link.url, key, sha, r.headers, fetched_at, commune.bfs_id, link.adapter)
    with _PUBLISH_LOCK:
        if pdf_path.exists():
            # same PDF reached through another URL: remember the URL, keep the first sidecar
            part.unlink()
            _index_add(index, entry)
            return None
        sidecar = RawSidecar(
            sha256=sha,
            source_url=fetched_url,
            listing_url=link.listing_url,
            commune_bfs_id=commune.bfs_id,
            body=link.body,
            fetched_at=fetched_at,
            etag=entry["etag"],
            last_modified=entry["last_modified"],
            content_type=r.headers.get("content-type") or None,
            size=size,
            listing_title=link.title,
            listing_date=link.date,
            adapter=link.adapter,
            upstream_id=link.upstream_id,
            date_precision=link.date_precision,
        )
        (settings.raw_dir / f"{sha}.json").write_text(sidecar.model_dump_json(indent=2))
        os.replace(part, pdf_path)
        _index_add(index, entry)
        return sha


def _open_document(
    link: DocumentLink, client: httpx.Client, polite: http.Politeness, headers: dict | None = None
) -> tuple[httpx.Response, str]:
    """The streaming response for a document and the URL that answered. `headers` are the
    conditional headers of a known document."""
    if not polite.allowed(link.url):
        raise http.FetchFailure("robots", link.url, "disallowed by robots.txt")
    url = link.url
    r = http._send(client, polite, client.build_request("GET", url, headers=headers), stream=True)
    http._ensure_ok(r, url)
    return r, url


def _stream_to_part(r: httpx.Response, url: str) -> tuple[str, int, Path]:
    """Write the body to a .part file in data/raw while hashing it; returns sha256, size and the
    part's path. The part is removed when anything fails."""
    declared = r.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_PDF_BYTES:
        raise http.FetchFailure("too_large", url, f"Content-Length {declared} over {MAX_PDF_BYTES}")
    part = settings.raw_dir / f"{hashlib.sha256(url.encode()).hexdigest()[:16]}.pdf.part"
    try:
        with part.open("wb") as f:
            sha, size = _copy_body(r, f, url)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    return sha, size, part


def _copy_body(r: httpx.Response, f, url: str) -> tuple[str, int]:
    """Stream the body into `f`. Rejects a body without the %PDF header in its first kilobyte (an
    error page served as application/pdf) and one over MAX_PDF_BYTES."""
    digest, size, head = hashlib.sha256(), 0, b""
    next_space_check = 0
    try:
        for chunk in r.iter_bytes(CHUNK_BYTES):
            if len(head) < 1024:
                head += chunk
                if len(head) >= 1024:
                    _require_pdf(head, r, url)
            size += len(chunk)
            if size > MAX_PDF_BYTES:
                raise http.FetchFailure("too_large", url, f"body over {MAX_PDF_BYTES} bytes")
            if size >= next_space_check:
                # Recheck while streaming in case another writer uses the disk.
                # A reserve error leaves the URL retryable and removes its part.
                storage.require_space(1024 * 1024)
                next_space_check = size + 1024 * 1024
            digest.update(chunk)
            f.write(chunk)
    except httpx.TimeoutException as exc:
        raise http.FetchFailure("timeout", url, http._describe(exc)) from exc
    except httpx.HTTPError as exc:
        raise http.FetchFailure("http", url, http._describe(exc)) from exc
    if len(head) < 1024:
        _require_pdf(head, r, url)
    return digest.hexdigest(), size


def _require_pdf(head: bytes, r: httpx.Response, url: str) -> None:
    if b"%PDF" not in head[:1024]:
        ctype = r.headers.get("content-type") or "unknown"
        raise http.FetchFailure("not_pdf", url, f"no PDF header (content-type {ctype})")


# --- decision pages ---------------------------------------------


def _download_page_locked(
    link: DocumentLink,
    commune: CommuneConfig,
    client: httpx.Client,
    polite: http.Politeness,
    index: dict[str, dict],
    volatile: Iterable[str],
    selector: str,
) -> str | None:
    """Fetch one decision page into data/raw as <sha>.html. Returns the sha256 of a new file, None
    when nothing is stored. Raises FetchFailure (robots, http, timeout, not_html, no_content,
    too_large).

    Unlike a PDF, a known page is requested again, conditionally with the held ETag and
    Last-Modified: its bytes change with menus and session tokens, and its decisions may change
    too. It is stored again only when the text of the `selector` element changed (content_sha256)."""
    key = canonical_url(link.url, volatile)
    known = index.get(key)
    if known and not held(known["sha256"]):
        known = None
    conditional = {}
    if known and known.get("etag"):
        conditional["If-None-Match"] = known["etag"]
    if known and known.get("last_modified"):
        conditional["If-Modified-Since"] = known["last_modified"]
    storage.require_space(MAX_HTML_BYTES)
    r, fetched_url = _open_document(link, client, polite, conditional or None)
    try:
        if r.status_code == 304 and known:
            return None
        body = _read_page(r, fetched_url)
    finally:
        r.close()
    content_type = r.headers.get("content-type") or None
    soup = html_document.page_soup(body, content_type)
    elements = html_document.content_elements(soup, selector)
    if not elements:
        # a changed layout must be noticed, not archived as an empty document
        raise http.FetchFailure(
            "no_content", fetched_url, f"content selector {selector!r} matches nothing"
        )
    content_sha = html_document.content_sha256(elements)
    if known and known.get("content_sha256") == content_sha:
        return None  # the same decisions in a page whose surroundings changed
    sha = hashlib.sha256(body).hexdigest()
    page_path = settings.raw_dir / f"{sha}.html"
    fetched_at = dt.datetime.now(dt.UTC)
    entry = _index_entry(
        link.url, key, sha, r.headers, fetched_at, commune.bfs_id, link.adapter, content_sha
    )
    with _PUBLISH_LOCK:
        if page_path.exists():
            _index_add(index, entry)
            return None
        sidecar = RawSidecar(
            sha256=sha,
            source_url=fetched_url,
            listing_url=link.listing_url,
            commune_bfs_id=commune.bfs_id,
            body=link.body,
            fetched_at=fetched_at,
            etag=entry["etag"],
            last_modified=entry["last_modified"],
            content_type=content_type,
            size=len(body),
            listing_title=link.title,
            listing_date=link.date,
            adapter=link.adapter,
            upstream_id=link.upstream_id,
            date_precision=link.date_precision,
            content_selector=selector,
            content_sha256=content_sha,
        )
        # as for PDFs: the sidecar first, so a page without a sidecar never exists on disk
        part = settings.raw_dir / f"{sha}.html.part"
        part.write_bytes(body)
        (settings.raw_dir / f"{sha}.json").write_text(sidecar.model_dump_json(indent=2))
        os.replace(part, page_path)
        _index_add(index, entry)
        return sha


def _read_page(r: httpx.Response, url: str) -> bytes:
    """The body of a decision page: a text/html content type and at most MAX_HTML_BYTES."""
    ctype = (r.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    if ctype != "text/html":
        raise http.FetchFailure("not_html", url, f"content-type {ctype or 'unknown'}")
    declared = r.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_HTML_BYTES:
        raise http.FetchFailure(
            "too_large", url, f"Content-Length {declared} over {MAX_HTML_BYTES}"
        )
    chunks, size = [], 0
    try:
        for chunk in r.iter_bytes(CHUNK_BYTES):
            size += len(chunk)
            if size > MAX_HTML_BYTES:
                raise http.FetchFailure("too_large", url, f"body over {MAX_HTML_BYTES} bytes")
            chunks.append(chunk)
    except httpx.TimeoutException as exc:
        raise http.FetchFailure("timeout", url, http._describe(exc)) from exc
    except httpx.HTTPError as exc:
        raise http.FetchFailure("http", url, http._describe(exc)) from exc
    return b"".join(chunks)
