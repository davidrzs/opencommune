//! The PDF catalogue (`pdf_catalog`, written by `opencommune catalog`): documents listed before
//! and without extraction, linked through `/original/<sha256>`.

use sqlx::{QueryBuilder, Sqlite, SqlitePool};

use super::contains_pattern;
use crate::models::{CatalogueItem, CataloguePage, CatalogueRow, linkable_url};

pub const PAGE_SIZE: i64 = 20;

/// `GET /api/archive/documents`: one page of a commune's catalogue, newest first, with the years
/// that have documents.
pub async fn documents(
    pool: &SqlitePool,
    commune: Option<i64>,
    q: &str,
    year: Option<i64>,
    offset: i64,
) -> sqlx::Result<CataloguePage> {
    let commune_filter = |qb: &mut QueryBuilder<Sqlite>| {
        if let Some(commune) = commune {
            qb.push(" AND commune_bfs_id = ").push_bind(commune);
        }
    };
    let mut qb = QueryBuilder::new(
        "SELECT DISTINCT CAST(substr(source_date, 1, 4) AS INTEGER) FROM pdf_catalog \
         WHERE source_date IS NOT NULL",
    );
    commune_filter(&mut qb);
    qb.push(" ORDER BY 1 DESC");
    let years: Vec<i64> = qb.build_query_scalar().fetch_all(pool).await?;

    let q = q.trim();
    let filters = |qb: &mut QueryBuilder<Sqlite>| {
        commune_filter(qb);
        if let Some(year) = year.filter(|y| *y != 0) {
            qb.push(" AND source_date >= ")
                .push_bind(format!("{year:04}-01-01"))
                .push(" AND source_date < ")
                .push_bind(format!("{:04}-01-01", year + 1));
        }
        if !q.is_empty() {
            qb.push(" AND lower(title) LIKE lower(")
                .push_bind(contains_pattern(q))
                .push(") ESCAPE '/'");
        }
    };
    let mut qb = QueryBuilder::new("SELECT count(*) FROM pdf_catalog WHERE 1");
    filters(&mut qb);
    let total: i64 = qb.build_query_scalar().fetch_one(pool).await?;

    let mut qb = QueryBuilder::new(
        "SELECT sha256, title, source_date, status, decision_count, source_url, body \
         FROM pdf_catalog WHERE 1",
    );
    filters(&mut qb);
    qb.push(" ORDER BY source_date DESC, sha256 LIMIT ")
        .push_bind(PAGE_SIZE)
        .push(" OFFSET ")
        .push_bind(offset);
    let rows: Vec<CatalogueRow> = qb.build_query_as().fetch_all(pool).await?;
    Ok(CataloguePage {
        total,
        years,
        items: rows.into_iter().map(CatalogueItem::from).collect(),
    })
}

/// `GET /original/{sha256}`: where a catalogued document lives on the commune's site.
pub async fn original(pool: &SqlitePool, sha256: &str) -> sqlx::Result<Option<String>> {
    let source: Option<Option<String>> =
        sqlx::query_scalar("SELECT source_url FROM pdf_catalog WHERE sha256 = ?")
            .bind(sha256)
            .fetch_optional(pool)
            .await?;
    Ok(source
        .flatten()
        .and_then(|url| linkable_url(Some(&url)).map(str::to_string)))
}
