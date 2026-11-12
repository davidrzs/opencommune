//! Decisions, published documents and archive statistics.

use serde::Serialize;
use serde_json::{Map, Value};
use sqlx::{AssertSqlSafe, QueryBuilder, Sqlite, SqlitePool};

use crate::models::{Decision, DecisionRow, DocumentItem, DocumentRow};

/// Below this many characters a query is matched with LIKE, not the full-text index.
const MIN_FTS_QUERY: usize = 3;

pub const CATEGORIES: [&str; 13] = [
    "zoning",
    "building_permit",
    "finance_budget",
    "finance_credit",
    "personnel",
    "infrastructure",
    "school",
    "social",
    "naturalization",
    "election",
    "bylaw",
    "procurement",
    "other",
];
pub const OUTCOMES: [&str; 4] = ["approved", "rejected", "postponed", "noted"];

/// `search.SearchFilters`. Dates are ISO strings, already validated.
#[derive(Debug, Default, Clone)]
pub struct SearchFilters {
    pub q: Option<String>,
    pub commune: Option<i64>,
    pub canton: Option<String>,
    pub category: Option<String>,
    pub outcome: Option<String>,
    pub lang: Option<String>,
    pub body: Option<String>,
    pub date_from: Option<String>,
    pub date_to: Option<String>,
    pub min_amount: Option<f64>,
    pub limit: i64,
    pub offset: i64,
}

pub struct SearchResult {
    pub items: Vec<Decision>,
    pub total: i64,
    pub mode: &'static str,
}

#[derive(Clone, Copy, PartialEq)]
enum Mode {
    Recent,
    Fts,
    Like,
}

impl Mode {
    fn name(self) -> &'static str {
        match self {
            Mode::Recent => "recent",
            Mode::Fts => "fts",
            Mode::Like => "like",
        }
    }
}

/// `search.fts_query`: quoted tokens, implicit AND, a prefix match on the last token.
pub fn fts_query(q: &str) -> Option<String> {
    let tokens: Vec<&str> = q
        .split(|c: char| !(c.is_alphanumeric() || c == '_'))
        .filter(|t| !t.is_empty())
        .collect();
    let (last, rest) = tokens.split_last()?;
    let mut parts: Vec<String> = rest.iter().map(|t| format!("\"{t}\"")).collect();
    parts.push(if last.chars().count() >= 3 {
        format!("\"{last}\"*")
    } else {
        format!("\"{last}\"")
    });
    Some(parts.join(" "))
}

const DECISION_COLUMNS: &str = "SELECT d.id, d.title, d.summary, d.category, d.outcome, \
    d.agenda_no, d.meeting_date, d.votes_for, d.votes_against, d.amount_chf, d.refs, \
    d.office_holders, d.page_start, d.page_end, d.language, d.confidence, \
    d.contains_private_individuals, d.redaction_applied, d.extraction_model, \
    d.extraction_version, c.bfs_id AS commune_bfs_id, c.name AS commune_name, \
    c.canton AS commune_canton, doc.id AS document_id, doc.body AS document_body, \
    doc.source_url AS document_source_url, \
    doc.provenance AS document_provenance, doc.sha256 AS document_sha256, \
    doc.pages AS document_pages, doc.title AS document_title";

const BASE_FROM: &str = " FROM decisions d JOIN communes c ON c.bfs_id = d.commune_bfs_id \
    JOIN documents doc ON doc.id = d.document_id";

/// FROM, joins and WHERE for a filter set in a given mode (`search._assemble`).
fn push_from_where(qb: &mut QueryBuilder<Sqlite>, f: &SearchFilters, mode: Mode, q: &str) {
    qb.push(BASE_FROM);
    if mode == Mode::Fts {
        qb.push(" JOIN decisions_fts fts ON fts.rowid = d.rid");
    }
    qb.push(" WHERE 1");
    if let Some(commune) = f.commune.filter(|c| *c != 0) {
        qb.push(" AND d.commune_bfs_id = ").push_bind(commune);
    }
    if let Some(canton) = f.canton.as_deref().filter(|s| !s.is_empty()) {
        qb.push(" AND c.canton = ").push_bind(canton.to_uppercase());
    }
    let text_filters = [
        (" AND d.category = ", &f.category),
        (" AND d.outcome = ", &f.outcome),
        (" AND d.language = ", &f.lang),
        (" AND doc.body = ", &f.body),
        (" AND d.meeting_date >= ", &f.date_from),
        (" AND d.meeting_date <= ", &f.date_to),
    ];
    for (clause, value) in text_filters {
        if let Some(v) = value.as_deref().filter(|s| !s.is_empty()) {
            qb.push(clause).push_bind(v.to_string());
        }
    }
    if let Some(amount) = f.min_amount.filter(|a| *a != 0.0) {
        qb.push(" AND d.amount_chf >= ").push_bind(amount);
    }
    match mode {
        Mode::Fts => {
            qb.push(" AND decisions_fts MATCH ")
                .push_bind(fts_query(q).unwrap_or_default());
        }
        Mode::Like => {
            let like = format!("%{q}%");
            qb.push(" AND (d.title LIKE ")
                .push_bind(like.clone())
                .push(" OR d.summary LIKE ")
                .push_bind(like)
                .push(")");
        }
        Mode::Recent => {}
    }
}

async fn count(pool: &SqlitePool, f: &SearchFilters, mode: Mode, q: &str) -> sqlx::Result<i64> {
    let mut qb = QueryBuilder::new("SELECT count(*)");
    push_from_where(&mut qb, f, mode, q);
    qb.build_query_scalar().fetch_one(pool).await
}

/// `search.search_decisions`: full-text search when the query is long enough and finds something,
/// else a LIKE match, else the most recent decisions.
pub async fn search(pool: &SqlitePool, f: &SearchFilters) -> sqlx::Result<SearchResult> {
    let q = f.q.as_deref().unwrap_or("").trim();
    let mut mode = Mode::Recent;
    let mut total = None;
    if q.chars().count() >= MIN_FTS_QUERY && fts_query(q).is_some() {
        let n = count(pool, f, Mode::Fts, q).await?;
        if n > 0 {
            mode = Mode::Fts;
            total = Some(n);
        }
    }
    if !q.is_empty() && mode != Mode::Fts {
        mode = Mode::Like;
    }
    let total = match total {
        Some(n) => n,
        None => count(pool, f, mode, q).await?,
    };
    let mut qb = QueryBuilder::new(DECISION_COLUMNS);
    push_from_where(&mut qb, f, mode, q);
    qb.push(match mode {
        Mode::Fts => " ORDER BY bm25(decisions_fts) ASC, d.meeting_date DESC",
        _ => " ORDER BY d.meeting_date DESC, d.rid ASC",
    });
    qb.push(" LIMIT ").push_bind(f.limit);
    qb.push(" OFFSET ").push_bind(f.offset);
    let rows: Vec<DecisionRow> = qb.build_query_as().fetch_all(pool).await?;
    Ok(SearchResult {
        items: rows.into_iter().map(Decision::from).collect(),
        total,
        mode: mode.name(),
    })
}

/// `search.get_decision`.
pub async fn get(pool: &SqlitePool, id: &str) -> sqlx::Result<Option<Decision>> {
    let sql = format!("{DECISION_COLUMNS}{BASE_FROM} WHERE d.id = ?");
    let row: Option<DecisionRow> = sqlx::query_as(AssertSqlSafe(sql))
        .bind(id)
        .fetch_optional(pool)
        .await?;
    Ok(row.map(Decision::from))
}

/// `search.list_documents`: published documents, newest meeting first.
pub async fn documents(
    pool: &SqlitePool,
    commune: Option<i64>,
    body: Option<&str>,
) -> sqlx::Result<Vec<DocumentItem>> {
    let mut qb = QueryBuilder::new(
        "SELECT doc.id, doc.commune_bfs_id, c.name AS commune_name, c.canton AS commune_canton, \
         doc.body, doc.meeting_date, doc.language, doc.pages, doc.ocr, doc.title, doc.source_url, \
         doc.provenance, doc.sha256, count(d.rid) AS decisions, \
         doc.dropped_decisions, doc.fetched_at \
         FROM documents doc JOIN communes c ON c.bfs_id = doc.commune_bfs_id \
         LEFT JOIN decisions d ON d.document_id = doc.id WHERE 1",
    );
    if let Some(commune) = commune.filter(|c| *c != 0) {
        qb.push(" AND doc.commune_bfs_id = ").push_bind(commune);
    }
    if let Some(body) = body.filter(|b| !b.is_empty()) {
        qb.push(" AND doc.body = ").push_bind(body.to_string());
    }
    qb.push(" GROUP BY doc.id ORDER BY doc.meeting_date DESC");
    let rows: Vec<DocumentRow> = qb.build_query_as().fetch_all(pool).await?;
    Ok(rows.into_iter().map(DocumentItem::from).collect())
}

#[derive(Serialize)]
pub struct CantonCount {
    canton: String,
    communes: i64,
    documents: i64,
    decisions: i64,
}

#[derive(Serialize)]
pub struct CategoryCount {
    category: String,
    decisions: i64,
}

#[derive(Serialize)]
pub struct RegisterSummary {
    communes: i64,
    by_status: Map<String, Value>,
    blocked: i64,
    examined: i64,
    reachable: i64,
    unreachable: i64,
}

#[derive(Serialize)]
pub struct Stats {
    communes: i64,
    communes_with_decisions: i64,
    communes_in_register: Option<i64>,
    register: RegisterSummary,
    by_health: Map<String, Value>,
    documents: i64,
    decisions: i64,
    decisions_dropped_for_privacy: i64,
    decisions_redacted: i64,
    date_min: Option<String>,
    date_max: Option<String>,
    approved_amount_chf: f64,
    by_canton: Vec<CantonCount>,
    by_category: Vec<CategoryCount>,
    by_outcome: Map<String, Value>,
    by_language: Map<String, Value>,
    by_body: Map<String, Value>,
    extraction_models: Map<String, Value>,
    categories: [&'static str; 13],
}

/// `register.STATUSES`, in order.
const REGISTER_STATUSES: [&str; 10] = [
    "configured",
    "candidate",
    "not_published",
    "not_found",
    "blocked_robots",
    "blocked_js",
    "blocked_network",
    "blocked_waf",
    "needs_feature",
    "not_examined",
];

/// Counts per value of a column; a NULL value is the key "None".
async fn counts(pool: &SqlitePool, sql: &'static str) -> sqlx::Result<Map<String, Value>> {
    let rows: Vec<(Option<String>, i64)> = sqlx::query_as(sql).fetch_all(pool).await?;
    Ok(rows
        .into_iter()
        .map(|(k, n)| (k.unwrap_or_else(|| "None".into()), Value::from(n)))
        .collect())
}

async fn scalar(pool: &SqlitePool, sql: &'static str) -> sqlx::Result<i64> {
    sqlx::query_scalar(sql).fetch_one(pool).await
}

/// `search.stats`. `communes_in_register` is the register's row count: the register has one row
/// per commune of the BFS snapshot (`opencommune register check`).
pub async fn stats(pool: &SqlitePool) -> sqlx::Result<Stats> {
    let (date_min, date_max): (Option<String>, Option<String>) =
        sqlx::query_as("SELECT min(meeting_date), max(meeting_date) FROM decisions")
            .fetch_one(pool)
            .await?;
    let by_canton: Vec<(String, i64, i64, i64)> = sqlx::query_as(
        "SELECT c.canton, count(DISTINCT c.bfs_id), count(DISTINCT doc.id), count(d.rid) \
         FROM communes c LEFT JOIN documents doc ON doc.commune_bfs_id = c.bfs_id \
         LEFT JOIN decisions d ON d.document_id = doc.id GROUP BY c.canton ORDER BY c.canton",
    )
    .fetch_all(pool)
    .await?;
    let by_category: Vec<(String, i64)> = sqlx::query_as(
        "SELECT category, count(*) FROM decisions GROUP BY category ORDER BY count(*) DESC",
    )
    .fetch_all(pool)
    .await?;
    let by_status: Vec<(String, i64)> =
        sqlx::query_as("SELECT status, count(*) FROM register GROUP BY status")
            .fetch_all(pool)
            .await?;
    let status_count = |s: &str| -> i64 {
        by_status
            .iter()
            .find(|(k, _)| k == s)
            .map_or(0, |(_, n)| *n)
    };
    let (in_register, reachable, unreachable): (i64, i64, i64) = sqlx::query_as(
        "SELECT count(*), coalesce(sum(reachable = 1), 0), coalesce(sum(reachable = 0), 0) \
         FROM register",
    )
    .fetch_one(pool)
    .await?;
    let register = RegisterSummary {
        communes: in_register,
        by_status: REGISTER_STATUSES
            .iter()
            .map(|s| (s.to_string(), Value::from(status_count(s))))
            .collect(),
        blocked: REGISTER_STATUSES
            .iter()
            .filter(|s| s.starts_with("blocked_"))
            .map(|s| status_count(s))
            .sum(),
        examined: by_status
            .iter()
            .filter(|(s, _)| s != "not_examined")
            .map(|(_, n)| n)
            .sum(),
        reachable,
        unreachable,
    };
    Ok(Stats {
        communes: scalar(pool, "SELECT count(*) FROM communes").await?,
        communes_with_decisions: scalar(
            pool,
            "SELECT count(DISTINCT commune_bfs_id) FROM decisions",
        )
        .await?,
        communes_in_register: (in_register > 0).then_some(in_register),
        register,
        by_health: counts(
            pool,
            "SELECT health, count(*) FROM holdings GROUP BY health",
        )
        .await?,
        documents: scalar(pool, "SELECT count(*) FROM documents").await?,
        decisions: scalar(pool, "SELECT count(*) FROM decisions").await?,
        decisions_dropped_for_privacy: scalar(
            pool,
            "SELECT coalesce(sum(dropped_decisions), 0) FROM documents",
        )
        .await?,
        decisions_redacted: scalar(
            pool,
            "SELECT count(*) FROM decisions WHERE redaction_applied = 1",
        )
        .await?,
        date_min,
        date_max,
        approved_amount_chf: sqlx::query_scalar(
            "SELECT CAST(coalesce(sum(amount_chf), 0) AS REAL) FROM decisions \
             WHERE outcome = 'approved'",
        )
        .fetch_one(pool)
        .await?,
        by_canton: by_canton
            .into_iter()
            .map(|(canton, communes, documents, decisions)| CantonCount {
                canton,
                communes,
                documents,
                decisions,
            })
            .collect(),
        by_category: by_category
            .into_iter()
            .map(|(category, decisions)| CategoryCount {
                category,
                decisions,
            })
            .collect(),
        by_outcome: counts(
            pool,
            "SELECT outcome, count(*) FROM decisions GROUP BY outcome",
        )
        .await?,
        by_language: counts(
            pool,
            "SELECT language, count(*) FROM decisions GROUP BY language",
        )
        .await?,
        by_body: counts(pool, "SELECT body, count(*) FROM documents GROUP BY body").await?,
        extraction_models: counts(
            pool,
            "SELECT extraction_model, count(*) FROM decisions GROUP BY extraction_model",
        )
        .await?,
        categories: CATEGORIES,
    })
}

#[cfg(test)]
mod tests {
    use super::fts_query;

    #[test]
    fn fts_queries_quote_tokens_and_prefix_the_last() {
        assert_eq!(
            fts_query("Kredit Schulhaus").as_deref(),
            Some("\"Kredit\" \"Schulhaus\"*")
        );
        assert_eq!(fts_query("ab").as_deref(), Some("\"ab\""));
        assert_eq!(
            fts_query("crédit d'école").as_deref(),
            Some("\"crédit\" \"d\" \"école\"*")
        );
        assert_eq!(fts_query("--- !"), None);
    }
}
