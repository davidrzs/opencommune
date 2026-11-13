"""Generic listing adapter: CSS selector + href/text regex per hop, date parsed from anchor text."""

from __future__ import annotations

import datetime as dt
import html as htmllib
import json
import re
import unicodedata
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

from bs4 import BeautifulSoup
from bs4.element import NavigableString, Tag

from ...schemas import AdapterStep
from ..html_parse import parse_html
from .base import Link, ListingAdapter, excluded


def is_pdf_candidate(anchor: Tag, url: str) -> bool:
    """Recognise linked PDF candidates; the downloader still validates file bytes."""
    parts = urlsplit(url)
    if (
        parts.path.lower().endswith((".pdf", ".pdf/download"))
        or anchor.get("type") == "application/pdf"
        or (anchor.get("download") or "").strip().lower().endswith(".pdf")
        or anchor.get_text(" ", strip=True).lower().endswith(".pdf")
    ):
        return True
    # Plone file listings use /download without a filename extension. Require
    # the MIME icon on this anchor, not a PDF icon elsewhere on the page.
    if parts.path.rstrip("/").endswith("/download") and anchor.select_one(
        ".icon-mimetype-mt-application-pdf"
    ):
        return True
    # Public Odoo document shares expose opaque download routes on their landing page.
    if (
        re.fullmatch(
            r"/document/download/[0-9]+/[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}/[0-9]+",
            parts.path,
            re.I,
        )
        and not parts.query
    ):
        return True
    if re.fullmatch(r"/FileDownload/Download/[0-9]+/?", parts.path, re.I):
        return True
    # i-web attachments use numeric IDs without filenames. Only consider links
    # actually published on the page; the downloader validates the PDF bytes.
    if re.fullmatch(r"/_doc/[0-9]+/?", parts.path):
        return True
    query = parse_qs(parts.query)
    # Municipal PHP download links retain their filename in the query. Keep
    # the published handler URL intact; the filename is not a relative path.
    if (
        parts.path.lower().endswith(".php")
        and set(query) == {"dl", "datei"}
        and query.get("dl") == ["1"]
    ):
        names = query.get("datei", [])
        if len(names) == 1 and re.fullmatch(r"[^/\\]+\.pdf", names[0], re.I):
            return True
    if parts.path.lower() == "/_iserv/dlfiles/dl.php" and set(query) == {"ddl"}:
        names = query["ddl"]
        if len(names) == 1 and re.fullmatch(r"[^/\\]+\.pdf", names[0], re.I):
            return True
    if re.fullmatch(r"/documents/dl/[0-9a-f]{8}(?:-[0-9a-f]{12}){2}/?", parts.path, re.I):
        return True
    if re.fullmatch(
        r"(?:/[^/]+)*/(?:index\.php/)?download_file/force/"
        r"(?:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9]+)/[0-9]+/?",
        parts.path,
        re.I,
    ):
        return True
    # JDownloads marks the document row and PDF icon; /send/ alone is too broad.
    if re.fullmatch(
        r"(?:/index\.php)?(?:/[^/]+)+/send/\d+-[a-z0-9-]+/\d+-[a-z0-9-]+/?",
        parts.path,
        re.I,
    ) and (
        "jd_download_url" in anchor.get("class", [])
        or any(
            re.search(
                r"/images/jdownloads/fileimages/(?:[^/]+/)*pdf\.png$", img.get("src", ""), re.I
            )
            for img in anchor.select("img[src]")
        )
        or (
            (container := anchor.find_parent(class_="jd_download_url")) is not None
            and container.parent is not None
            and any(
                re.search(
                    r"/images/jdownloads/fileimages/(?:[^/]+/)*pdf\.png$",
                    img.get("src", ""),
                    re.I,
                )
                for img in container.parent.select("img[src]")
            )
        )
    ):
        return True
    if parts.path.lower().endswith("/cdws/dok.php") and query.get("typ") == ["pdf"]:
        did = query.get("did", [])
        if len(did) == 1 and re.fullmatch(r"(?:[0-9]+|[0-9a-f]{32}-[0-9]+)", did[0], re.I):
            return True
    # Municipal download handlers may carry the PDF name in a structured query.
    if parts.path.lower() == "/appl/download.php" and query.get("cmd") == ["viewinline"]:
        filename = query.get("filename", [])
        if (
            len(filename) == 1
            and filename[0].lower().endswith(".pdf")
            and all(
                len(query.get(key, [])) == 1 and query[key][0].isdigit()
                for key in ("objid", "id", "nr", "usid")
            )
        ):
            return True
    # Indual/phpComasy files use hexadecimal resource IDs, not filename extensions.
    if query.get("action") == ["get_file"] and all(
        len(query.get(key, [])) == 1 and re.fullmatch(r"[0-9a-f]+", query[key][0], re.I)
        for key in ("id", "resource_link_id")
    ):
        return True
    # Phoca Download can mount category pages at arbitrary municipal paths. The
    # PDF MIME icon on the file row supplies the type when its label omits .pdf.
    phoca_pdf_icon = any(
        "pd-document16" in parent.get("class", [])
        and "/media/com_phocadownload/images/mime/16/icon-pdf.png"
        in parent.get("style", "").lower()
        for parent in list(anchor.parents)[:4]
        if isinstance(parent, Tag)
    )
    # Phoca Download's category pages link files through an ID and slug.
    if (
        ("/category/" in parts.path or phoca_pdf_icon)
        and len(query.get("download", [])) == 1
        and re.fullmatch(r"\d+:[\w-]+", query["download"][0])
    ):
        return True
    if parts.path.lower().endswith("/downdoc.php"):
        return len(query.get("id_doc", [])) == 1 and query["id_doc"][0].isdigit()
    # WordPress Simple Download Monitor, including a spelling used by municipal sites.
    if any(query.get(key) == ["1"] for key in ("sdm_process_download", "smd_process_download")):
        return len(query.get("download_id", [])) == 1 and query["download_id"][0].isdigit()
    # Assolo documents have opaque URLs. Some omit ?i=1 but retain document classes.
    document_class = bool({"ListDocLink", "ObjListDocLink"} & set(anchor.get("class", [])))
    opaque_id = re.search(r"-[0-9a-f]{8}$", parts.path, re.I)
    return bool(document_class or (opaque_id and query.get("i") == ["1"]))


_MONTHS = {
    # de
    "januar": 1,
    "februar": 2,
    "märz": 3,
    "maerz": 3,
    "april": 4,
    "mai": 5,
    "juni": 6,
    "juli": 7,
    "august": 8,
    "september": 9,
    "oktober": 10,
    "november": 11,
    "dezember": 12,
    "jan": 1,
    "feb": 2,
    "mrz": 3,
    "mär": 3,
    "apr": 4,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "okt": 10,
    "nov": 11,
    "dez": 12,
    # fr
    "janvier": 1,
    "février": 2,
    "fevrier": 2,
    "mars": 3,
    "avril": 4,
    "juin": 6,
    "juillet": 7,
    "août": 8,
    "aout": 8,
    "septembre": 9,
    "octobre": 10,
    "novembre": 11,
    "décembre": 12,
    "decembre": 12,
    "janv": 1,
    "févr": 2,
    "fevr": 2,
    "avr": 4,
    "juil": 7,
    "oct": 10,
    "déc": 12,
    "dec": 12,
    # it
    "gennaio": 1,
    "febbraio": 2,
    "marzo": 3,
    "aprile": 4,
    "maggio": 5,
    "giugno": 6,
    "luglio": 7,
    "agosto": 8,
    "settembre": 9,
    "ottobre": 10,
    "dicembre": 12,
    "gen": 1,
    "mar": 3,
    "mag": 5,
    "giu": 6,
    "lug": 7,
    "ago": 8,
    "set": 9,
    "ott": 10,
    "dic": 12,
}
# A month name or abbreviation must stand on its own: "gen" inside "Gemeindeversammlungen" is not
# gennaio, "mar" inside "Markt" is not March.
_MONTH_RE = (
    "(?<![a-zäöüéèàçA-ZÄÖÜ])(?:"
    + "|".join(sorted(map(re.escape, _MONTHS), key=len, reverse=True))
    + ")(?![a-zäöüéèàçA-ZÄÖÜ])"
)
# "30. Januar 2025", "1er avril 2026", "16. Jun. 2025", "15-16 giugno 2026" (the second day)
_NAMED_DATE = re.compile(
    rf"(?<!\d)(\d{{1,2}})\.?[\s_+-]*(?:er)?[\s_+-]*({_MONTH_RE})\.?[\s_+-]*(\d{{4}}|\d{{2}}(?!\d))",
    re.IGNORECASE,
)
# The two separators of a date must be the same character: "4. Dezember 2002 04.12.2002" holds no
# "2002 04.12". Named groups keep the day, month and year addressable next to the separator group.
_ISO_DATE = re.compile(
    r"(?<!\d)(?P<y>(?:19|20)\d{2})(?P<s>[-_. ])(?P<m>\d{2})(?P=s)(?P<d>\d{2})(?!\d)"
)  # 2026-05-18, 2026 04 22
_DMY_DATE = re.compile(
    r"(?<!\d)(?P<d>\d{1,2})(?P<s>[./_-])(?P<m>\d{1,2})(?P=s)(?P<y>(?:19|20)\d{2})(?!\d)"
)  # 3.7.2025, 22_01_2025
_HEX_RUN = re.compile(r"[0-9a-f]{32,}")  # a digest used as file name, never a date
_COMPACT_YMD = re.compile(r"(?<!\d)(?P<y>(?:19|20)\d{2})(?P<m>\d{2})(?P<d>\d{2})(?!\d)")  # 20260519
_COMPACT_DMY = re.compile(r"(?<!\d)(?P<d>\d{2})(?P<m>\d{2})(?P<y>(?:19|20)\d{2})(?!\d)")  # 05122023
_DMY_SHORT = re.compile(
    r"(?<![\d.])(?P<d>\d{1,2})(?P<s>[./])(?P<m>\d{1,2})(?P=s)(?P<y>\d{2})(?![.\d]?\d)"
)  # 29.06.15
_MONTH_YEAR = re.compile(
    rf"(?<![\d.])({_MONTH_RE})\.?[\s_+-]*((?:19|20)\d{{2}})(?!\d)", re.IGNORECASE
)
_NAMED_DM = re.compile(
    rf"(?<!\d)(\d{{1,2}})\.?[\s_+-]*(?:er)?[\s_+-]*({_MONTH_RE})\b", re.IGNORECASE
)
_URL_YEAR = re.compile(r"/((?:19|20)\d{2})/")
# Shapes in order of trust. The two-digit-year shape is kept apart: a file name such as
# "05.07.26-P.V.-21.04.26" reads as a date either way, so a full date elsewhere (the enclosing row)
# must be consulted first.
_SHAPES_FULL: tuple[re.Pattern[str], ...] = (
    _ISO_DATE,
    _DMY_DATE,
    _NAMED_DATE,
    _COMPACT_YMD,
    _COMPACT_DMY,
)
_SHAPES_SHORT: tuple[re.Pattern[str], ...] = (_DMY_SHORT,)


def _from_match(m: re.Match[str]) -> dt.date | None:
    if m.re is _NAMED_DATE:
        return _safe_date(int(m[3]), _MONTHS[m[2].lower()], int(m[1]))
    return _safe_date(int(m["y"]), int(m["m"]), int(m["d"]))


def parse_date(
    text: str,
    date_regex: str | None = None,
    order: str = "dmy",
    *,
    short_years: bool = True,
    shapes: bool = True,
) -> dt.date | None:
    """Exact (day-precision) date from anchor text or URL. Custom regex first, then the common shapes.
    Among the full shapes the earliest valid match in the text wins ("02-12-2025-03-12-2025" starts
    with a day-first date, the year-first reading inside it is an artefact); shape order breaks ties.
    Every match of a shape is tried, so an invalid one does not hide a later valid one.
    `short_years=False` leaves out the dd.mm.yy shape, which is only tried when no full shape matched.
    `shapes=False` tries the custom regex only."""
    if date_regex:
        for m in re.finditer(date_regex, text):
            groups = m.groups()[:3]
            if len(groups) != 3 or not all(groups):
                continue
            # the middle group is the month and may be a month name ("cm_pv_2024_avril_16")
            month = groups[1].lower()
            g = [
                int(groups[0]) if groups[0].isdigit() else None,
                int(month) if month.isdigit() else _MONTHS.get(month),
                int(groups[2]) if groups[2].isdigit() else None,
            ]
            if None in g:
                continue
            y, mo, d = (g[0], g[1], g[2]) if order == "ymd" else (g[2], g[1], g[0])
            found = _safe_date(y, mo, d)
            if found:
                return found
    if not shapes:
        return None
    for group in (_SHAPES_FULL, _SHAPES_SHORT if short_years else ()):
        best: tuple[int, dt.date] | None = None
        for pattern in group:
            for m in pattern.finditer(text):
                found = _from_match(m)
                if found:
                    if best is None or m.start() < best[0]:
                        best = (m.start(), found)
                    break
        if best is not None:
            return best[1]
    return None


def parse_month_year(text: str) -> dt.date | None:
    """A month name followed by a year ("Juni 2026", "juin-2019"), as the first of that month. Only
    for callers that record the precision: the day is a placeholder, not a fact."""
    for m in _MONTH_YEAR.finditer(text):
        found = _safe_date(int(m[2]), _MONTHS[m[1].lower()], 1)
        if found:
            return found
    return None


def parse_date_with_url(text: str, url: str, date_regex: str | None, order: str) -> dt.date | None:
    """Anchor text first, then the URL, then day+month in the text combined with a year in the URL."""
    return _first_date([text], url, date_regex, order)


def _first_date(
    texts: list[str], url: str, date_regex: str | None, order: str, short_years: bool = True
) -> dt.date | None:
    """The texts in order, then the URL, then day+month in a text combined with a year in the URL.
    The URL is unquoted first: an encoded space before a date (`%2011.06.2026`) otherwise reads as 2011."""
    # a content-addressed file name (a 64-hex digest on a CDN) never carries a date, but its digits
    # can spell one; blank such runs before reading the URL
    url = _HEX_RUN.sub(" ", unquote(url))
    for text in texts:
        found = parse_date(text, date_regex, order, short_years=short_years)
        if found:
            return found
    found = parse_date(url, date_regex, order, short_years=short_years)
    if found:
        return found
    y = _URL_YEAR.search(url)
    if y:
        for text in texts:
            m = _NAMED_DM.search(text)
            if m:
                return _safe_date(int(y[1]), _MONTHS[m[2].lower()], int(m[1]))
    return None


def _first_month(texts: list[str]) -> dt.date | None:
    for text in texts:
        found = parse_month_year(text)
        if found:
            return found
    return None


# Anchor texts that label the link rather than the document; the `title` attribute is used instead.
_GENERIC_TEXT = re.compile(
    r"^(?:(?:pdf|download(?:en)?|herunterladen|hier|here|ici|qui|link|mehr erfahren|mehr lesen|mehr|"
    r"weiterlesen|weiter|details?|öffnen|ansehen|anzeigen|datei|dokument|document|documento|fichier|"
    r"télécharger|telecharger|lire la suite|lire|consulter|voir|ouvrir|en savoir plus|scarica(?:re)?|"
    r"apri|leggi|file|read more|open|view)\W*)+$",
    re.IGNORECASE,
)
# File-size tails that some CMSs append to the link text: "[pdf, 162 KB]", "Fichier PDF (212.84 Ko)", "0.88 MB".
_SIZE_TAIL = re.compile(
    r"\s*(?:(?:fichier\s+)?(?:pdf|docx?)?\s*[\[(](?:pdf|docx?)?,?\s*[\d.,']+\s*[kmg]?[bo][\])]|[\d.,']+\s*[kmg]b|[\[(](?:pdf|docx?)[\])])\s*$",
    re.IGNORECASE,
)


# Soft hyphens (`&shy;`), zero-width spaces and joiners, the word joiner and the byte-order mark.
_INVISIBLE = dict.fromkeys(map(ord, "\u00ad\u200b\u200c\u200d\u2060\ufeff"))


def clean_text(value: str) -> str:
    """Text as a regex expects it: NFC-normalised (a decomposed umlaut becomes one code point),
    without soft hyphens and zero-width characters, whitespace collapsed, file-size tail removed."""
    value = unicodedata.normalize("NFC", value).translate(_INVISIBLE)
    return _SIZE_TAIL.sub("", " ".join(value.split()))


def _anchor_texts(a) -> tuple[str, str]:
    """The anchor's own text and its `title` (or `aria-label`) attribute, both cleaned."""
    text = clean_text(a.get_text(" ", strip=True))
    title = clean_text(a.get("title") or a.get("aria-label") or "")
    return text, title


_ROW_TAGS = ("tr", "li", "p")
# "Beschlüsse der Gemeindeversammlung vom 10. Dezember 2025": the date after such a word is the
# meeting's, a date before it is usually the publication date.
_MEETING_WORD = re.compile(r"\b(?:vom|du|del|dal|della)\s+(\S.{0,40})", re.IGNORECASE)
_TITLE_LIMIT = 200


def _row_text(node: Tag, own: str) -> str:
    """Text of the closest table row, list item or paragraph around `node`, minus the node's own text.
    A paragraph is cut at its `<br>` elements, so the part that holds the node is one item. When the
    node sits in a table cell that carries a date of its own, the cell is the item: a row may list
    several documents side by side, each with its date."""
    cell = node.find_parent(("td", "th"))
    if cell is not None:
        cell_text = clean_text(cell.get_text(" "))
        cell_text = cell_text.replace(own, " ", 1) if own else cell_text
        if parse_date(cell_text):
            return cell_text
    row = node.find_parent(_ROW_TAGS)
    if row is None:
        return ""
    parts: list[str] = []
    seen = False
    for d in row.descendants:
        if d is node:
            seen = True
        if row.name == "p" and isinstance(d, Tag) and d.name == "br":
            if seen:
                break
            parts = []
        elif type(d) is NavigableString:
            parts.append(str(d))
    # a list entry often repeats its title (a visible and a hidden copy); keep the first
    unique: dict[str, None] = {}
    for part in parts:
        part = " ".join(part.split())
        if part and (len(part) <= 12 or part not in unique):
            unique[part + f"\0{len(unique)}" if len(part) <= 12 else part] = None
    text = clean_text(" ".join(key.split("\0")[0] for key in unique))
    if own:
        text = clean_text(text.replace(own, " ", 1))
    return text


def _heading_text(node: Tag) -> str:
    """The nearest heading before the link in document order: accordion and section pages put the
    meeting date there ("Gemeindeversammlung vom 17.06.2026") and nothing on the links."""
    heading = node.find_previous(["h1", "h2", "h3", "h4", "h5", "h6"])
    return clean_text(heading.get_text(" ", strip=True)) if heading else ""


def _row_title(row: str) -> str:
    if len(row) <= _TITLE_LIMIT:
        return row
    return row[:_TITLE_LIMIT].rsplit(" ", 1)[0]


def _meeting_first(row: str) -> list[str]:
    """The row text with the part after "vom", "du" or "del" tried first."""
    m = _MEETING_WORD.search(row)
    return [m[1], row] if m else [row]


def _safe_date(y: int, m: int, d: int) -> dt.date | None:
    """A date from 1990 to 2100, else None. A two-digit year is read in this century unless that
    lies beyond next year ("24.07.96" is 1996). Later four-digit years are kept as written: the
    fetch driver decides what a future date means."""
    if y < 100:
        y += 2000 if 2000 + y <= dt.date.today().year + 1 else 1900
    try:
        if 1990 <= y <= 2100:
            return dt.date(y, m, d)
    except ValueError:
        return None
    return None


_DATA_ENTITIES = re.compile(r'data-entities="([^"]*)"')
_ANCHOR = re.compile(r"<a\s[^>]*>.*?</a>", re.DOTALL)
_DATE_IN_TEXT = re.compile(r"\d{1,2}\.\d{1,2}\.\d{4}|\d{4}-\d{2}-\d{2}")


def _row_fragment(row: dict, row_dates: bool = True) -> str | None:
    """One table row -> its anchors, each carrying the row's date cell text so dates survive
    (unless `row_dates` is off: the column is a publication date the title should not take)."""
    anchors: list[str] = []
    other_text: list[str] = []
    for value in row.values():
        if not isinstance(value, str) or value.startswith("#"):
            continue
        if "<a " in value:
            anchors.extend(_ANCHOR.findall(value))
        else:
            text = " ".join(BeautifulSoup(value, "html.parser").get_text(" ", strip=True).split())
            if text:
                other_text.append(text)
    if not anchors:
        return None
    dated = " ".join(t for t in other_text if _DATE_IN_TEXT.search(t)) if row_dates else ""
    out = []
    for a in anchors:
        if dated and not _DATE_IN_TEXT.search(a):
            a = a.replace("</a>", f" {dated}</a>", 1)
        out.append(a)
    return " ".join(out)


def unpack_embedded_tables(html: str, row_dates: bool = True) -> str:
    """i-web pages embed their sortable tables as JSON in a `data-entities` attribute whose cells
    are HTML fragments. Append those rows to the document so normal selectors see the anchors;
    `row_dates` as in _row_fragment."""
    fragments: list[str] = []

    def walk(value) -> None:
        if isinstance(value, dict):
            frag = _row_fragment(value, row_dates)
            if frag:
                fragments.append(frag)
                return
            for v in value.values():
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)

    for raw in _DATA_ENTITIES.findall(html):
        try:
            walk(json.loads(htmllib.unescape(raw)))
        except ValueError:
            continue
    if not fragments:
        return html
    return html + '<div class="embedded-table-links">' + "\n".join(fragments) + "</div>"


# `onclick="location.href='/x.pdf'"`, `window.location = "..."`, `window.open("...")`
_ONCLICK_URL = re.compile(r"""(?:location(?:\.href)?\s*=|\bopen\s*\()\s*['"]([^'"]+)['"]""")
_SKIP_HREF = ("#", "javascript:", "mailto:", "tel:")


def _href(node: Tag) -> str | None:
    """The URL an element leads to: its href, the URL in its onclick handler when the href is
    missing or a placeholder (`#`, `javascript:`), or the text of a sitemap `<loc>` entry."""
    if node.name == "loc":
        loc = node.get_text(strip=True)
        return loc if loc.startswith(("http://", "https://")) else None
    href = (node.get("href") or "").strip() if node.name == "a" else ""
    if href and not href.startswith(_SKIP_HREF):
        return href
    for script in (href if href.startswith("javascript:") else "", node.get("onclick") or ""):
        m = _ONCLICK_URL.search(script)
        if m:
            return m[1]
    return None


def _candidates(el: Tag):
    """(element, href) pairs under a selected element: the element itself when it leads somewhere
    (an anchor, or a row whose onclick navigates), otherwise every descendant that does."""
    href = _href(el)
    if href:
        yield el, href
        return
    for node in el.find_all(True):
        href = _href(node)
        if href:
            yield node, href


def _base_href(soup: BeautifulSoup, base_url: str) -> str:
    """`<base href>` when the page declares one; relative hrefs resolve against it, not the page URL."""
    base = soup.find("base", href=True)
    return urljoin(base_url, base["href"]) if base else base_url


def unwrap_viewer(url: str) -> str:
    """Some sites link PDFs through an in-page viewer (`viewer.php?file=<pdf url>`); use the file."""
    parts = urlsplit(url)
    if parts.query and ("viewer" in parts.path or "file=" in parts.query):
        for key in ("file", "url", "src"):
            for value in parse_qs(parts.query).get(key, []):
                if value.lower().split("?")[0].endswith(".pdf"):
                    return urljoin(url, value)
    return url


class HtmlLinksAdapter(ListingAdapter):
    name = "html_links"

    def extract_links(
        self,
        html: str,
        base_url: str,
        step: AdapterStep,
        date_regex: str | None,
        date_order: str,
        parent: Link | None = None,
    ) -> list[Link]:
        soup = parse_html(unpack_embedded_tables(html, step.table_row_dates))
        base_url = _base_href(soup, base_url)
        url_re = re.compile(step.url_regex, re.IGNORECASE) if step.url_regex else None
        text_re = re.compile(step.text_regex, re.IGNORECASE) if step.text_regex else None
        drop_re = re.compile(step.exclude_regex, re.IGNORECASE) if step.exclude_regex else None
        seen: set[str] = set()
        links: list[Link] = []
        for el in soup.select(step.selector):
            if step.url_attribute:
                value = (el.get(step.url_attribute) or "").strip()
                pairs = [(el, value)] if value else []
            else:
                pairs = list(_candidates(el))
            for a, href in pairs:
                url = unwrap_viewer(urljoin(base_url, href))
                text, title = _anchor_texts(a)
                own = [t for t in (text, title) if t]
                if step.context == "row":
                    row = _row_text(a, text)
                elif step.context == "heading":
                    row = _heading_text(a)
                else:
                    row = ""
                if not text or _GENERIC_TEXT.match(text):
                    text = title or _row_title(row) or text
                if url_re and not url_re.search(url):
                    continue
                if text_re and not text_re.search(text):
                    continue
                if excluded(drop_re, text + " " + url):
                    continue
                if url in seen:
                    continue
                seen.add(url)
                date, precision, context_date = None, "day", None
                # full dates first, from the link and then its row; two-digit years only after that
                for short_years in (False, True):
                    date = None
                    if step.prefer_context_date and row:
                        # the configured regex on the link and URL first (a session date in the
                        # file name), then the context, before any generic date shape of the URL
                        if date_regex:
                            date = next(
                                (
                                    d
                                    for t in [*own, unquote(url)]
                                    if (d := parse_date(t, date_regex, date_order, shapes=False))
                                ),
                                None,
                            )
                        if date is None:
                            date = _first_date(
                                _meeting_first(row), "", date_regex, date_order, short_years
                            )
                            context_date = date
                    if date is None:
                        date = _first_date(own, url, date_regex, date_order, short_years)
                    if date is None and row:
                        date = _first_date(
                            _meeting_first(row), url, date_regex, date_order, short_years
                        )
                        context_date = date
                    if date is not None:
                        break
                if date is None:
                    date = _first_month([*own, unquote(url)])
                    if date is None and row:
                        date = _first_month([row])
                        context_date = date
                    if date is not None:
                        precision = "month"
                        if (
                            parent is not None
                            and parent.date is not None
                            and parent.date_precision == "day"
                            and (parent.date.year, parent.date.month) == (date.year, date.month)
                        ):
                            # the folder or session link names the day within that month
                            date, precision, context_date = parent.date, "day", parent.date
                if date is None and parent is not None and parent.date is not None:
                    # a document without a date of its own belongs to the session whose link led here
                    date, precision, context_date = parent.date, parent.date_precision, parent.date
                links.append(
                    Link(
                        url=url,
                        text=text,
                        date=date,
                        date_precision=precision,
                        context_date=context_date,
                    )
                )
        return links

    def next_url(self, content: str, url: str, step: AdapterStep, headers=None) -> str | None:
        """The page the step's `next_selector` points at (an anchor, a `<link rel=next>` or an element
        holding the anchor), or None on the last page."""
        if not step.next_selector:
            return None
        soup = parse_html(content)
        el = soup.select_one(step.next_selector)
        if el is not None and el.name not in ("a", "link"):
            el = el.find("a", href=True)
        if el is None:
            return None
        href = (el.get("href") or "").strip()
        if not href or href.startswith(("#", "javascript:")):
            return None
        target = urljoin(_base_href(soup, url), href)
        return None if target == url else target
