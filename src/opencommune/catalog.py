"""Index PDF availability without requiring or inventing a decision record."""

import datetime as dt
import json
import logging
import re
import unicodedata
from pathlib import Path
from urllib.parse import unquote, urlsplit

from sqlalchemy import delete, func, select

from .config import settings
from .models import CatalogPDF, Commune, Decision, Document
from .schemas import RawSidecar

log = logging.getLogger(__name__)
STATUSES = {
    "pending_parse": "PDF vorhanden · noch nicht ausgelesen",
    "pending_extract": "Noch nicht in Beschlüsse aufgeteilt",
    "pending_publication": "Beschlüsse noch nicht veröffentlicht",
    "published": "Beschlüsse verfügbar",
    "no_decisions": "Keine relevanten Beschlüsse erkannt",
    "withheld": "Keine Beschlüsse veröffentlicht",
    "unavailable": "Verarbeitungsstand unklar",
}
SHA = re.compile(r"^[0-9a-f]{64}$")
BATCH_SIZE = 500
LATEST_AFTER_FETCH = dt.timedelta(days=366)
NEUTRAL_TITLE = "Gemeindedokument"
# Naturalisation documents stay out of the catalogue: a link shows its URL, and some URLs and
# titles name the applicant.
NATURALISATION = re.compile(
    r"einb(?:u|ue|\u00fc)rger|naturali[sz]|b(?:u|ue|\u00fc)rgerrecht|droit[\W_]+de[\W_]+cit"
    r"|attinenz|cittadinanz",
    re.IGNORECASE,
)
# Fixed labels, so that no word of an unreviewed file name or title is ever shown.
# The first match wins; texts are lower case without accents.
LABELS = [
    (r"traktand", "Traktanden"),
    (r"ordre.du.jour", "Ordre du jour"),
    (r"ordine.del.giorno", "Ordine del giorno"),
    (r"protokoll", "Protokoll"),
    (r"proces.?verba|(?<![a-z])pv(?![a-z])", "Procès-verbal"),
    (r"verbale", "Verbale"),
    (r"jahresrechnung", "Jahresrechnung"),
    (r"(?<![a-z])comptes?(?![a-z])", "Comptes"),
    (r"consuntiv", "Consuntivo"),
    (r"voranschlag", "Voranschlag"),
    (r"preventiv", "Preventivo"),
    (r"budget", "Budget"),
    (r"gesch(?:ae|a)ftsbericht", "Geschäftsbericht"),
    (r"jahresbericht", "Jahresbericht"),
    (r"rapport.{0,20}gestion", "Rapport de gestion"),
    (r"rapporto.{0,20}gestione", "Rapporto di gestione"),
    (r"botschaft", "Botschaft"),
    (r"preavis", "Préavis"),
    (r"messaggio|(?<![a-z])mm(?![a-z])", "Messaggio municipale"),
    (r"regolament", "Regolamento"),
    (r"verordnung", "Verordnung"),
    (r"reglement", "Reglement"),
]
LABELS = [(re.compile(pattern), label) for pattern, label in LABELS]
YEAR = re.compile(r"(?<!\d)(?:19[5-9]\d|20[0-3]\d)(?!\d)")
COUNCIL_PAGE = re.compile(r"traktand|gesch(?:ae|\u00e4)ft|sitzung", re.IGNORECASE)


def _write_batch(session, batch, indexed_at):
    """Flush a bounded number of rows without retaining catalogue ORM objects."""
    rows = {
        row.sha256: row
        for row in session.scalars(
            select(CatalogPDF).where(CatalogPDF.sha256.in_([sha for sha, _ in batch]))
        )
    }
    touched = []
    for sha, values in batch:
        row = rows.get(sha)
        if row is None:
            row = CatalogPDF(sha256=sha)
            session.add(row)
            changed = True
        else:
            changed = any(getattr(row, key) != value for key, value in values.items())
        if changed:
            for key, value in values.items():
                setattr(row, key, value)
            row.indexed_at = indexed_at
        touched.append(row)
    session.flush()
    for row in touched:
        session.expunge(row)


def safe_url(value):
    try:
        parsed = urlsplit(value or "")
        return value if parsed.scheme in ("https", "http") and parsed.netloc else None
    except ValueError:
        return None


def document_label(sidecar) -> str:
    """A label from a fixed list and a year, read from the file name and the listing title; the
    neutral label when neither names a known kind of document."""
    name = unquote(urlsplit(sidecar.source_url).path).rsplit("/", 1)[-1]
    text = unicodedata.normalize("NFKD", f"{sidecar.listing_title} {name}")
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    label = next((label for pattern, label in LABELS if pattern.search(text)), None)
    if label is None:
        return NEUTRAL_TITLE
    year = YEAR.search(text)
    return f"{label} {year.group()}" if year else label


def _is_print_view(sidecar) -> bool:
    """GOViS renders any page as a PDF at .../print/pdf: service desk products, staff and contact
    pages are not documents; agenda items, council business and sessions are."""
    url = unquote(sidecar.source_url)
    return "/print/pdf" in url and not COUNCIL_PAGE.search(url)


def _about_naturalisation(sidecar) -> bool:
    """True when the URL or listing title concerns naturalisation; such a document is not listed.
    Matches forms and reports too: those stay on the commune's own site."""
    texts = (sidecar.source_url, sidecar.listing_title)
    return any(NATURALISATION.search(unicodedata.normalize("NFC", unquote(text))) for text in texts)


def upsert_communes(session, communes) -> None:
    """The configured communes as `communes` rows (name, canton, website, coordinates)."""
    for c in communes:
        row = session.get(Commune, c.bfs_id) or Commune(bfs_id=c.bfs_id)
        row.name = c.name
        row.canton = c.canton
        row.language = c.language
        row.website = c.website
        row.vendor = c.vendor
        row.minutes_url = c.listing_urls[0] if c.listing_urls else None
        row.publicity_regime = c.publicity_regime
        row.lat = c.lat
        row.lon = c.lon
        session.add(row)


def extracted_decisions(path: Path) -> int:
    """The number of decisions in an extraction output (`data/extracted/<sha>.json`). Raises
    ValueError for a file that is not one."""
    try:
        decisions = json.loads(path.read_text())["result"]["decisions"]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"not an extraction output: {path.name}") from exc
    if not isinstance(decisions, list):
        raise ValueError(f"not an extraction output: {path.name}")
    return len(decisions)


def refresh(session, communes):
    """One transaction, built from the sidecars: a document is listed by its link to the commune's
    site, whether or not this machine holds the PDF. Also removes stale entries."""
    known = {c.bfs_id: c for c in session.scalars(select(Commune))}
    known.update({c.bfs_id: c for c in communes})
    # The verified register supplies identity; raw, validated PDFs establish archive coverage.
    # The catalogue never writes the register and never guesses a language.
    from .register import load_register

    registered = {c.bfs_id: c for c in load_register()}
    from .crawl.wordpress import load_sources

    archive_sources = {c.bfs_id: c for c in load_sources()}
    from .crawl import linked_archive

    linked_sources = {c.bfs_id: c for c in linked_archive.load_sources()}

    counts = dict(
        session.execute(
            select(Decision.document_id, func.count()).group_by(Decision.document_id)
        ).all()
    )
    published = {d.sha256: d for d in session.scalars(select(Document))}
    # Only retain keys. Loading the entire catalogue as ORM rows keeps hundreds of
    # thousands of objects alive until commit and makes each refresh memory-heavy.
    stale = set(session.scalars(select(CatalogPDF.sha256)))
    batch = []
    count = 0
    indexed_at = dt.datetime.now(dt.UTC).replace(tzinfo=None)
    for path in settings.raw_dir.glob("*.json"):
        sha = path.stem
        if not SHA.fullmatch(sha):
            continue
        try:
            sidecar = RawSidecar.model_validate_json(path.read_text())
            if sidecar.sha256 != sha:
                raise ValueError("sidecar hash mismatch")
        except (OSError, ValueError):
            log.warning("catalogue: invalid sidecar for %s", sha[:12])
            continue
        # HTML decision pages are counted beside the catalogue, not in it
        if (
            sidecar.content_selector is not None
            or _about_naturalisation(sidecar)
            or _is_print_view(sidecar)
        ):
            continue
        c = known.get(sidecar.commune_bfs_id)
        if c is None:
            entry = registered.get(sidecar.commune_bfs_id)
            if entry is None or sidecar.body != "unknown":
                continue
            linked = linked_sources.get(entry.bfs_id)
            linked_ok = (
                linked is not None
                and linked.website == entry.website
                and linked.vendor == entry.vendor
                and linked.accepts_sidecar(sidecar)
            )
            if linked_ok:
                pass
            elif entry.vendor == "wordpress":
                source = archive_sources.get(entry.bfs_id)
                if source is None or source.website != entry.website:
                    continue
            elif entry.vendor != "i-web":
                continue
            from .crawl.iweb import same_site

            if not entry.website or (
                not linked_ok and not same_site(sidecar.listing_url, entry.website)
            ):
                continue
            c = Commune(
                bfs_id=entry.bfs_id,
                name=entry.name,
                canton=entry.canton,
                website=entry.website,
                language="",
                vendor=entry.vendor,
            )
            session.add(c)
            known[c.bfs_id] = c
        stale.discard(sha)
        count += 1
        doc = published.get(sha)
        status = "pending_parse"
        n = 0
        if (settings.parsed_dir / f"{sha}.json").exists():
            status = "pending_extract"
        ex_path = settings.extracted_dir / f"{sha}.json"
        if ex_path.exists():
            try:
                n = extracted_decisions(ex_path)
                status = "pending_publication" if n else "no_decisions"
            except (OSError, ValueError):
                status = "unavailable"
        if doc:
            n = counts.get(doc.id, 0)
            status = "published" if n else "withheld" if doc.dropped_decisions else "no_decisions"
        # a date more than a year after the download is a misreading (a file number, a year-first
        # file name read day-first) and is recorded as unknown
        date = doc.meeting_date if doc else sidecar.listing_date
        if date is not None and date > sidecar.fetched_at.date() + LATEST_AFTER_FETCH:
            date = None
        batch.append(
            (
                sha,
                {
                    "commune_bfs_id": c.bfs_id,
                    "commune_name": c.name,
                    "canton": c.canton,
                    "body": doc.body if doc else sidecar.body,
                    "source_date": date,
                    "date_precision": "day" if doc and doc.meeting_date else sidecar.date_precision,
                    "title": doc.title if doc else document_label(sidecar),
                    "source_url": safe_url(sidecar.source_url),
                    "provenance": sidecar.adapter or "html_links",
                    "status": status,
                    "decision_count": n if status == "published" else 0,
                },
            )
        )
        if len(batch) >= BATCH_SIZE:
            _write_batch(session, batch, indexed_at)
            batch.clear()
    if batch:
        _write_batch(session, batch, indexed_at)
    stale_keys = list(stale)
    for start in range(0, len(stale_keys), BATCH_SIZE):
        keys = stale_keys[start : start + BATCH_SIZE]
        session.execute(
            delete(CatalogPDF).where(CatalogPDF.sha256.in_(keys)),
            execution_options={"synchronize_session": "fetch"},
        )
    session.flush()
    return count


def html_documents() -> int:
    """Decision pages stored as HTML. The catalogue lists PDFs only; these are
    counted beside it, not catalogued."""
    return sum(1 for p in settings.raw_dir.glob("*.html") if SHA.fullmatch(p.stem))
