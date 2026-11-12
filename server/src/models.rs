//! Database rows (`FromRow`) and the JSON the API returns. Field names and order are part of the
//! API (`API.md`).

use serde::Serialize;
use serde_json::Value;
use sqlx::FromRow;

// --- decisions --------------------------------------------------------------------------------

#[derive(FromRow)]
pub struct DecisionRow {
    pub id: String,
    pub title: String,
    pub summary: String,
    pub category: String,
    pub outcome: Option<String>,
    pub agenda_no: Option<String>,
    pub meeting_date: Option<String>,
    pub votes_for: Option<i64>,
    pub votes_against: Option<i64>,
    pub amount_chf: Option<f64>,
    pub refs: Option<String>,
    pub office_holders: Option<String>,
    pub page_start: i64,
    pub page_end: i64,
    pub language: String,
    pub confidence: Option<f64>,
    pub contains_private_individuals: bool,
    pub redaction_applied: bool,
    pub extraction_model: String,
    pub extraction_version: String,
    pub commune_bfs_id: i64,
    pub commune_name: String,
    pub commune_canton: String,
    pub document_id: String,
    pub document_body: String,
    pub document_source_url: String,
    pub document_provenance: String,
    pub document_sha256: String,
    pub document_pages: i64,
    pub document_title: String,
}

#[derive(Serialize)]
pub struct CommuneRef {
    pub bfs_id: i64,
    pub name: String,
    pub canton: String,
}

#[derive(Serialize)]
pub struct DecisionDocument {
    pub id: String,
    pub body: String,
    pub source_url: String,
    pub provenance: String,
    pub sha256: String,
    pub pages: i64,
    pub title: String,
}

#[derive(Serialize)]
pub struct Decision {
    pub id: String,
    pub title: String,
    pub summary: String,
    pub category: String,
    pub outcome: Option<String>,
    pub agenda_no: Option<String>,
    pub meeting_date: Option<String>,
    pub votes_for: Option<i64>,
    pub votes_against: Option<i64>,
    pub amount_chf: Option<f64>,
    pub references: Value,
    pub office_holders: Value,
    pub page_start: i64,
    pub page_end: i64,
    pub language: String,
    pub confidence: Option<f64>,
    pub contains_private_individuals: bool,
    pub redaction_applied: bool,
    pub extraction_model: String,
    pub extraction_version: String,
    pub commune: CommuneRef,
    pub document: DecisionDocument,
    pub source_link: String,
}

impl From<DecisionRow> for Decision {
    fn from(r: DecisionRow) -> Self {
        let source_link = format!("{}#page={}", r.document_source_url, r.page_start);
        Decision {
            id: r.id,
            title: r.title,
            summary: r.summary,
            category: r.category,
            outcome: r.outcome,
            agenda_no: r.agenda_no,
            meeting_date: r.meeting_date,
            votes_for: r.votes_for,
            votes_against: r.votes_against,
            amount_chf: r.amount_chf,
            references: json_list(r.refs.as_deref()),
            office_holders: json_list(r.office_holders.as_deref()),
            page_start: r.page_start,
            page_end: r.page_end,
            language: r.language,
            confidence: r.confidence,
            contains_private_individuals: r.contains_private_individuals,
            redaction_applied: r.redaction_applied,
            extraction_model: r.extraction_model,
            extraction_version: r.extraction_version,
            commune: CommuneRef {
                bfs_id: r.commune_bfs_id,
                name: r.commune_name,
                canton: r.commune_canton,
            },
            document: DecisionDocument {
                id: r.document_id,
                body: r.document_body,
                source_url: r.document_source_url,
                provenance: r.document_provenance,
                sha256: r.document_sha256,
                pages: r.document_pages,
                title: r.document_title,
            },
            source_link,
        }
    }
}

#[derive(Serialize)]
pub struct SearchPage {
    pub total: i64,
    pub mode: &'static str,
    pub limit: i64,
    pub offset: i64,
    pub items: Vec<Decision>,
}

// --- documents ---------------------------------------------------------------------------------

#[derive(FromRow)]
pub struct DocumentRow {
    pub id: String,
    pub commune_bfs_id: i64,
    pub commune_name: String,
    pub commune_canton: String,
    pub body: String,
    pub meeting_date: Option<String>,
    pub language: String,
    pub pages: i64,
    pub ocr: bool,
    pub title: String,
    pub source_url: String,
    pub provenance: String,
    pub sha256: String,
    pub decisions: i64,
    pub dropped_decisions: i64,
    pub fetched_at: String,
}

#[derive(Serialize)]
pub struct DocumentItem {
    pub id: String,
    pub commune: CommuneRef,
    pub body: String,
    pub meeting_date: Option<String>,
    pub language: String,
    pub pages: i64,
    pub ocr: bool,
    pub title: String,
    pub source_url: String,
    pub provenance: String,
    pub sha256: String,
    pub decisions: i64,
    pub dropped_decisions: i64,
    pub fetched_at: String,
}

impl From<DocumentRow> for DocumentItem {
    fn from(r: DocumentRow) -> Self {
        DocumentItem {
            id: r.id,
            commune: CommuneRef {
                bfs_id: r.commune_bfs_id,
                name: r.commune_name,
                canton: r.commune_canton,
            },
            body: r.body,
            meeting_date: r.meeting_date,
            language: r.language,
            pages: r.pages,
            ocr: r.ocr,
            title: r.title,
            source_url: r.source_url,
            provenance: r.provenance,
            sha256: r.sha256,
            decisions: r.decisions,
            dropped_decisions: r.dropped_decisions,
            fetched_at: iso_datetime(&r.fetched_at),
        }
    }
}

// --- catalogue ---------------------------------------------------------------------------------

#[derive(FromRow)]
pub struct CatalogueRow {
    pub sha256: String,
    pub title: String,
    pub source_date: Option<String>,
    pub status: String,
    pub decision_count: i64,
    pub source_url: Option<String>,
    pub body: String,
}

#[derive(Serialize)]
pub struct CatalogueItem {
    pub id: String,
    pub title: String,
    pub date: Option<String>,
    pub status: String,
    pub decisions: i64,
    /// `/original/<sha256>`, never the commune's URL.
    pub url: Option<String>,
    pub body: String,
}

impl From<CatalogueRow> for CatalogueItem {
    fn from(r: CatalogueRow) -> Self {
        let linkable = linkable_url(r.source_url.as_deref()).is_some();
        CatalogueItem {
            url: linkable.then(|| format!("/original/{}", r.sha256)),
            id: r.sha256,
            title: r.title,
            date: r.source_date,
            status: r.status,
            decisions: r.decision_count,
            body: r.body,
        }
    }
}

#[derive(Serialize)]
pub struct CataloguePage {
    pub total: i64,
    pub years: Vec<i64>,
    pub items: Vec<CatalogueItem>,
}

// --- communes ----------------------------------------------------------------------------------

#[derive(FromRow)]
pub struct HoldingRow {
    pub commune_bfs_id: i64,
    pub body: String,
    pub kinds: Option<String>,
    pub documents: i64,
    pub undated: i64,
    pub parsed: i64,
    pub extracted: i64,
    pub records: i64,
    pub decisions: i64,
    pub first_date: Option<String>,
    pub last_date: Option<String>,
    pub per_year: Option<String>,
    pub expected_interval_days: Option<f64>,
    pub gaps: Option<String>,
    pub stale: bool,
    pub listed_not_held: i64,
    pub last_crawl: Option<String>,
    pub last_result: Option<String>,
    pub health: String,
    pub register_status: Option<String>,
    pub register_note: Option<String>,
    pub available_from: Option<String>,
}

#[derive(Serialize)]
pub struct Holding {
    pub body: String,
    pub kinds: Value,
    pub documents: i64,
    pub undated: i64,
    pub parsed: i64,
    pub extracted: i64,
    pub records: i64,
    pub decisions: i64,
    pub first_date: Option<String>,
    pub last_date: Option<String>,
    pub per_year: Value,
    pub per_year_average: Option<f64>,
    pub expected_interval_days: Option<f64>,
    pub gaps: Value,
    pub stale: bool,
    pub listed_not_held: i64,
    pub last_crawl: Option<String>,
    pub last_result: Option<String>,
    pub health: String,
    pub register_status: Option<String>,
    pub register_note: Option<String>,
    pub available_from: Option<String>,
}

impl From<HoldingRow> for Holding {
    fn from(h: HoldingRow) -> Self {
        let year = |d: &Option<String>| d.as_deref().and_then(|d| d.get(..4)?.parse::<i64>().ok());
        let span = match (year(&h.first_date), year(&h.last_date)) {
            (Some(first), Some(last)) => last - first + 1,
            _ => 0,
        };
        Holding {
            per_year_average: (span != 0)
                .then(|| round1((h.documents - h.undated) as f64 / span as f64)),
            body: h.body,
            kinds: json_list(h.kinds.as_deref()),
            documents: h.documents,
            undated: h.undated,
            parsed: h.parsed,
            extracted: h.extracted,
            records: h.records,
            decisions: h.decisions,
            first_date: h.first_date,
            last_date: h.last_date,
            per_year: json_or(h.per_year.as_deref(), Value::Object(Default::default())),
            expected_interval_days: h.expected_interval_days,
            gaps: json_list(h.gaps.as_deref()),
            stale: h.stale,
            listed_not_held: h.listed_not_held,
            last_crawl: h.last_crawl.as_deref().map(iso_datetime),
            last_result: h.last_result,
            health: h.health,
            register_status: h.register_status,
            register_note: h.register_note,
            available_from: h.available_from,
        }
    }
}

#[derive(FromRow)]
pub struct CommuneRow {
    pub bfs_id: i64,
    pub name: String,
    pub canton: String,
    pub language: String,
    pub website: String,
    pub vendor: Option<String>,
    pub minutes_url: Option<String>,
    pub publicity_regime: Option<String>,
    pub last_crawled: Option<String>,
    pub lat: Option<f64>,
    pub lon: Option<f64>,
    pub documents: i64,
    pub decisions: i64,
    pub register_status: Option<String>,
    pub register_note: Option<String>,
}

/// One row of `GET /api/communes` (`search.list_communes`).
#[derive(Serialize)]
pub struct Commune {
    pub bfs_id: i64,
    pub name: String,
    pub canton: String,
    pub language: String,
    pub website: String,
    pub vendor: Option<String>,
    pub minutes_url: Option<String>,
    pub publicity_regime: Option<String>,
    pub last_crawled: Option<String>,
    pub lat: Option<f64>,
    pub lon: Option<f64>,
    pub documents: i64,
    pub decisions: i64,
    pub holdings: Vec<Holding>,
    pub register_status: Option<String>,
    pub register_note: Option<String>,
}

impl Commune {
    pub fn new(c: CommuneRow, holdings: Vec<Holding>) -> Self {
        // the newest crawl of any body, else the commune's own date
        let last_crawled = holdings
            .iter()
            .filter_map(|h| h.last_crawl.clone())
            .max()
            .or_else(|| c.last_crawled.as_deref().map(iso_datetime));
        Commune {
            bfs_id: c.bfs_id,
            name: c.name,
            canton: c.canton,
            language: c.language,
            website: c.website,
            vendor: c.vendor,
            minutes_url: c.minutes_url,
            publicity_regime: c.publicity_regime,
            last_crawled,
            lat: c.lat,
            lon: c.lon,
            documents: c.documents,
            decisions: c.decisions,
            holdings,
            register_status: c.register_status,
            register_note: c.register_note,
        }
    }
}

#[derive(FromRow, Serialize)]
pub struct Access {
    pub status: String,
    pub checked_at: String,
    pub robots_url: String,
    pub restricted_at: Option<String>,
    pub source_url: String,
    pub stale: bool,
}

/// A commune on the commune page (`GET /api/archive/communes/{bfs_id}`): the commune list's row
/// with the catalogue's document count and the access observations, or, for a commune that is only
/// in the register, the few fields the register has.
#[derive(Serialize)]
#[serde(untagged)]
pub enum ArchiveCommune {
    Covered {
        #[serde(flatten)]
        commune: Commune,
        access: Vec<Access>,
    },
    RegisterOnly {
        bfs_id: i64,
        name: String,
        canton: String,
        website: Option<String>,
        documents: i64,
        decisions: i64,
        holdings: Vec<Holding>,
        access: Vec<Access>,
    },
}

#[derive(FromRow)]
pub struct SlimRow {
    pub bfs_id: i64,
    pub name: String,
    pub canton: String,
    pub lat: Option<f64>,
    pub lon: Option<f64>,
    pub documents: i64,
    pub decisions: i64,
    pub catalogue: i64,
    pub held: Option<i64>,
}

#[derive(FromRow, Serialize)]
pub struct SlimAccess {
    #[serde(skip)]
    pub bfs_id: i64,
    pub status: String,
    pub stale: bool,
    pub restricted_at: Option<String>,
}

/// A commune on the map and in the commune list (`GET /api/archive/communes`).
#[derive(Serialize)]
pub struct SlimCommune {
    pub bfs_id: i64,
    pub name: String,
    pub canton: String,
    pub lat: Option<f64>,
    pub lon: Option<f64>,
    pub documents: i64,
    pub decisions: i64,
    pub access: Vec<SlimAccess>,
}

// --- register ----------------------------------------------------------------------------------

#[derive(FromRow)]
pub struct RegisterRow {
    pub bfs_id: i64,
    pub name: String,
    pub canton: String,
    pub status: String,
    pub website: Option<String>,
    pub vendor: Option<String>,
    pub reachable: Option<bool>,
    pub checked: Option<String>,
    pub checked_by: Option<String>,
    pub notes: Option<String>,
}

#[derive(FromRow, Serialize)]
pub struct Publication {
    #[serde(skip)]
    pub bfs_id: i64,
    pub body: String,
    pub kind: String,
    pub status: String,
    pub listing_url: Option<String>,
    pub from: Option<String>,
    pub to: Option<String>,
    pub cadence: Option<String>,
    pub obstacle: Option<String>,
    pub how: Option<String>,
}

#[derive(Serialize)]
pub struct RegisterEntry {
    pub bfs_id: i64,
    pub name: String,
    pub canton: String,
    pub status: String,
    pub website: Option<String>,
    pub vendor: Option<String>,
    pub reachable: Option<bool>,
    pub checked: Option<String>,
    pub checked_by: Option<String>,
    pub notes: Option<String>,
    pub publications: Vec<Publication>,
}

impl RegisterEntry {
    pub fn new(r: RegisterRow, publications: Vec<Publication>) -> Self {
        RegisterEntry {
            bfs_id: r.bfs_id,
            name: r.name,
            canton: r.canton,
            status: r.status,
            website: r.website,
            vendor: r.vendor,
            reachable: r.reachable,
            checked: r.checked,
            checked_by: r.checked_by,
            notes: r.notes,
            publications,
        }
    }
}

// --- helpers -----------------------------------------------------------------------------------

/// A JSON list column; null or unreadable gives `[]` (Python: `d.refs or []`).
pub fn json_list(text: Option<&str>) -> Value {
    json_or(text, Value::Array(Vec::new()))
}

fn json_or(text: Option<&str>, empty: Value) -> Value {
    match text.and_then(|t| serde_json::from_str::<Value>(t).ok()) {
        Some(Value::Null) | None => empty,
        Some(v) => v,
    }
}

/// SQLAlchemy stores `2026-09-07 23:10:36.404587`; Python's `isoformat()` gives
/// `2026-09-07T23:10:36.404587`, without the fraction when it is zero.
pub fn iso_datetime(stored: &str) -> String {
    let iso = stored.replacen(' ', "T", 1);
    match iso.split_once('.') {
        Some((head, fraction)) if fraction.bytes().all(|b| b == b'0') => head.to_string(),
        _ => iso,
    }
}

/// Python's `round(x, 1)`: the exact binary value rounded half to even, as `format!` does.
pub fn round1(x: f64) -> f64 {
    format!("{x:.1}").parse().unwrap_or(x)
}

/// The URL a document redirects to (`catalog.safe_url`): its source URL when that is an absolute
/// http(s) URL.
pub fn linkable_url(source: Option<&str>) -> Option<&str> {
    let url = source.filter(|u| !u.is_empty())?;
    let (scheme, rest) = url.split_once(':')?;
    let scheme_ok = scheme.eq_ignore_ascii_case("http") || scheme.eq_ignore_ascii_case("https");
    let netloc = rest.strip_prefix("//")?.split(['/', '?', '#']).next()?;
    // urlsplit raises on an unbalanced IPv6 bracket; safe_url then gives None
    let brackets_ok = netloc.contains('[') == netloc.contains(']');
    (scheme_ok && brackets_ok && !netloc.is_empty()).then_some(url)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn datetimes_print_like_python() {
        assert_eq!(
            iso_datetime("2026-09-07 23:10:36.404587"),
            "2026-09-07T23:10:36.404587"
        );
        assert_eq!(
            iso_datetime("2026-09-07 23:10:36.000000"),
            "2026-09-07T23:10:36"
        );
    }

    #[test]
    fn rounding_matches_python() {
        assert_eq!(round1(1.25), 1.2); // exact tie: half to even
        assert_eq!(round1(23.0 / 20.0), 1.1); // 1.15 is stored just below the tie
        assert_eq!(round1(4.0 / 3.0), 1.3);
    }

    #[test]
    fn only_absolute_http_urls_are_linked() {
        assert!(linkable_url(Some("https://a.ch/x.pdf")).is_some());
        assert_eq!(linkable_url(Some("http://b.ch/y")), Some("http://b.ch/y"));
        assert!(linkable_url(Some("")).is_none());
        assert!(linkable_url(Some("ftp://a.ch/x")).is_none());
        assert!(linkable_url(Some("https:///x")).is_none());
        assert!(linkable_url(Some("/relative")).is_none());
        assert!(linkable_url(None).is_none());
    }
}
