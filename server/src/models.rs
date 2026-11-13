//! Database rows (`FromRow`) and the JSON the API returns. Field names and order are part of the
//! API (`API.md`).

use rmcp::schemars::JsonSchema;
use serde::Serialize;
use serde_json::Value;
use sqlx::FromRow;

// --- communes ----------------------------------------------------------------------------------

/// One row of `GET /api/communes`.
#[derive(FromRow, Serialize, JsonSchema)]
#[schemars(crate = "rmcp::schemars")]
pub struct Commune {
    pub bfs_id: i64,
    pub name: String,
    pub canton: String,
    pub language: Option<String>,
    pub website: Option<String>,
    pub lat: Option<f64>,
    pub lon: Option<f64>,
    pub documents: i64,
    pub register_status: Option<String>,
    pub register_note: Option<String>,
}

/// `GET /api/communes/{bfs_id}`: the commune with its register entry and access observations.
#[derive(FromRow, Serialize, JsonSchema)]
#[schemars(crate = "rmcp::schemars")]
pub struct CommuneDetail {
    pub bfs_id: i64,
    pub name: String,
    pub canton: String,
    pub language: Option<String>,
    pub website: Option<String>,
    pub vendor: Option<String>,
    pub lat: Option<f64>,
    pub lon: Option<f64>,
    pub documents: i64,
    #[sqlx(skip)]
    pub register: Option<RegisterEntry>,
    #[sqlx(skip)]
    pub access: Vec<Access>,
    /// Documents per year and section family, newest year first.
    #[sqlx(skip)]
    pub holdings: Vec<Holding>,
}

/// How many of a commune's documents of a year have a section of a family.
#[derive(FromRow, Serialize, JsonSchema)]
#[schemars(crate = "rmcp::schemars")]
pub struct Holding {
    pub year: i64,
    pub family: String,
    pub documents: i64,
}

/// A commune named by a document or a page.
#[derive(FromRow, Serialize, JsonSchema)]
#[schemars(crate = "rmcp::schemars")]
pub struct CommuneRef {
    pub bfs_id: i64,
    pub name: String,
    pub canton: String,
}

#[derive(FromRow, Serialize, JsonSchema)]
#[schemars(crate = "rmcp::schemars")]
pub struct Access {
    pub status: String,
    pub checked_at: String,
    pub robots_url: String,
    pub restricted_at: Option<String>,
    pub source_url: String,
    pub stale: bool,
}

// --- documents ---------------------------------------------------------------------------------

#[derive(FromRow)]
pub struct DocumentRow {
    pub sha256: String,
    pub title: Option<String>,
    pub body_name: Option<String>,
    pub first_seen: String,
    pub listing_date: Option<String>,
    pub date: Option<String>,
    pub year: Option<i64>,
    pub years: Option<String>,
    pub page_count: Option<i64>,
    pub pages_seen: Option<i64>,
    pub run_id: String,
    pub body_kind: Option<String>,
    pub languages: Option<String>,
    pub personal_data: bool,
}

#[derive(FromRow, Serialize, JsonSchema)]
#[schemars(crate = "rmcp::schemars")]
pub struct Section {
    #[serde(skip)]
    pub sha256: String,
    #[serde(rename = "type")]
    pub section_type: String,
    /// deliberation, money, proposals, rules, information or other.
    pub family: String,
    pub first_page: i64,
    pub last_page: i64,
    pub partly_unseen: bool,
}

/// A document in `GET /api/documents` and the MCP tools.
#[derive(Serialize, JsonSchema)]
#[schemars(crate = "rmcp::schemars")]
pub struct Document {
    pub sha256: String,
    /// As printed, as the classifier read it; private names appear as [name].
    pub title: Option<String>,
    /// The body as printed, as the classifier read it.
    pub body_name: Option<String>,
    pub first_seen: String,
    pub listing_date: Option<String>,
    pub date: Option<String>,
    pub year: Option<i64>,
    pub years: Vec<i64>,
    pub page_count: Option<i64>,
    pub pages_seen: Option<i64>,
    pub run_id: String,
    pub body_kind: Option<String>,
    pub languages: Vec<String>,
    pub personal_data: bool,
    /// In the order the classifier gave them.
    pub sections: Vec<Section>,
    /// The communes that link the document, by name.
    pub communes: Vec<CommuneRef>,
    /// `/original/<sha256>`, never a commune's URL.
    pub original_url: String,
}

impl Document {
    pub fn new(r: DocumentRow, sections: Vec<Section>, communes: Vec<CommuneRef>) -> Self {
        Document {
            original_url: format!("/original/{}", r.sha256),
            sha256: r.sha256,
            title: r.title,
            body_name: r.body_name,
            first_seen: r.first_seen,
            listing_date: r.listing_date,
            date: r.date,
            year: r.year,
            // a part that is not a year is left out
            years: list(r.years.as_deref())
                .filter_map(|y| y.parse().ok())
                .collect(),
            page_count: r.page_count,
            pages_seen: r.pages_seen,
            run_id: r.run_id,
            body_kind: r.body_kind,
            languages: list(r.languages.as_deref()).map(str::to_string).collect(),
            personal_data: r.personal_data,
            sections,
            communes,
        }
    }
}

/// `GET /api/documents/{sha256}`: the document and the run that classified it.
#[derive(Serialize, JsonSchema)]
#[schemars(crate = "rmcp::schemars")]
pub struct DocumentDetail {
    #[serde(flatten)]
    pub document: Document,
    pub run: Option<RunRef>,
}

/// How many documents have a value.
#[derive(Serialize, JsonSchema)]
#[schemars(crate = "rmcp::schemars", rename = "Count_{T}")]
pub struct Count<T> {
    pub value: Option<T>,
    pub count: i64,
}

#[derive(Serialize, JsonSchema)]
#[schemars(crate = "rmcp::schemars")]
pub struct Facets {
    pub years: Vec<Count<i64>>,
    pub sections: Vec<Count<String>>,
    pub bodies: Vec<Count<String>>,
}

/// `GET /api/documents` and the MCP tool `search_documents`.
#[derive(Serialize, JsonSchema)]
#[schemars(crate = "rmcp::schemars")]
pub struct DocumentPage {
    pub total: i64,
    pub offset: i64,
    pub limit: i64,
    pub facets: Facets,
    pub items: Vec<Document>,
}

// --- runs --------------------------------------------------------------------------------------

/// The run named by a document.
#[derive(FromRow, Serialize, JsonSchema)]
#[schemars(crate = "rmcp::schemars")]
pub struct RunRef {
    pub id: String,
    pub stage: String,
    pub model: Option<String>,
    pub note: String,
}

#[derive(FromRow)]
pub struct RunRow {
    pub id: String,
    pub stage: String,
    pub model: Option<String>,
    pub settings: String,
    pub note: String,
    pub documents: i64,
}

/// One row of `GET /api/runs`.
#[derive(Serialize, JsonSchema)]
#[schemars(crate = "rmcp::schemars")]
pub struct Run {
    pub id: String,
    pub stage: String,
    pub model: Option<String>,
    pub settings: Value,
    pub note: String,
    pub documents: i64,
}

impl From<RunRow> for Run {
    fn from(r: RunRow) -> Self {
        Run {
            id: r.id,
            stage: r.stage,
            model: r.model,
            // unreadable JSON gives null
            settings: serde_json::from_str(&r.settings).unwrap_or(Value::Null),
            note: r.note,
            documents: r.documents,
        }
    }
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

#[derive(FromRow, Serialize, JsonSchema)]
#[schemars(crate = "rmcp::schemars")]
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

#[derive(Serialize, JsonSchema)]
#[schemars(crate = "rmcp::schemars")]
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

// --- crawler-facing pages ----------------------------------------------------------------------

/// The archive's totals on the start page and in `/llms.txt`.
#[derive(FromRow)]
pub struct PageTotals {
    pub documents: i64,
    pub communes: i64,
}

// --- helpers -----------------------------------------------------------------------------------

/// The parts of a comma-separated column; NULL gives none.
fn list(text: Option<&str>) -> impl Iterator<Item = &str> {
    text.unwrap_or("")
        .split(',')
        .map(str::trim)
        .filter(|part| !part.is_empty())
}

/// The URL a document redirects to: its source URL when that is an absolute http(s) URL.
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
    fn comma_separated_columns_become_lists() {
        assert_eq!(
            list(Some("2024, 2025")).collect::<Vec<_>>(),
            ["2024", "2025"]
        );
        assert_eq!(list(Some("")).count(), 0);
        assert_eq!(list(None).count(), 0);
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
