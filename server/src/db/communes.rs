//! Communes, the register and the access observations.

use std::collections::HashMap;

use sqlx::{QueryBuilder, Sqlite, SqlitePool};

use crate::models::{Commune, CommuneDetail, Publication, RegisterEntry, RegisterRow};

/// Every commune of the archive, by canton and name, with its number of documents and its
/// register status.
pub async fn list(pool: &SqlitePool) -> sqlx::Result<Vec<Commune>> {
    sqlx::query_as(
        "SELECT c.bfs_id, c.name, c.canton, c.language, c.website, c.lat, c.lon, \
         (SELECT count(*) FROM document_communes dc WHERE dc.bfs_id = c.bfs_id) AS documents, \
         r.status AS register_status, r.note AS register_note \
         FROM communes c LEFT JOIN register r ON r.bfs_id = c.bfs_id \
         ORDER BY c.canton, c.name",
    )
    .fetch_all(pool)
    .await
}

/// One commune of the archive with its register entry and its access observations, newest
/// check first; None when the archive does not have it. An observation whose last restriction
/// or check is a week old or more is stale.
pub async fn detail(pool: &SqlitePool, bfs_id: i64) -> sqlx::Result<Option<CommuneDetail>> {
    let commune: Option<CommuneDetail> = sqlx::query_as(
        "SELECT c.bfs_id, c.name, c.canton, c.language, c.website, c.vendor, c.lat, c.lon, \
         (SELECT count(*) FROM document_communes dc WHERE dc.bfs_id = c.bfs_id) AS documents \
         FROM communes c WHERE c.bfs_id = ?",
    )
    .bind(bfs_id)
    .fetch_optional(pool)
    .await?;
    let Some(mut commune) = commune else {
        return Ok(None);
    };
    commune.register = entries(pool, Some(bfs_id)).await?.pop();
    commune.access = sqlx::query_as(
        "SELECT status, checked_at, robots_url, restricted_at, source_url, \
         julianday('now') - julianday(coalesce(restricted_at, checked_at)) >= 7 AS stale \
         FROM access_observations WHERE bfs_id = ? ORDER BY checked_at DESC",
    )
    .bind(bfs_id)
    .fetch_all(pool)
    .await?;
    commune.holdings = sqlx::query_as(
        "SELECT d.year, s.family, count(DISTINCT d.sha256) AS documents FROM documents d \
         JOIN sections s ON s.sha256 = d.sha256 \
         JOIN document_communes dc ON dc.sha256 = d.sha256 \
         WHERE dc.bfs_id = ? AND d.year IS NOT NULL \
         GROUP BY d.year, s.family ORDER BY d.year DESC, s.family",
    )
    .bind(bfs_id)
    .fetch_all(pool)
    .await?;
    Ok(Some(commune))
}

/// Every commune of the register with its publications.
pub async fn register(pool: &SqlitePool) -> sqlx::Result<Vec<RegisterEntry>> {
    entries(pool, None).await
}

/// Register entries by canton and BFS id with their publications in file order: all, or one
/// commune's.
async fn entries(pool: &SqlitePool, bfs_id: Option<i64>) -> sqlx::Result<Vec<RegisterEntry>> {
    let only = |qb: &mut QueryBuilder<Sqlite>| {
        if let Some(bfs_id) = bfs_id {
            qb.push(" WHERE bfs_id = ").push_bind(bfs_id);
        }
    };
    let mut qb = QueryBuilder::new(
        "SELECT bfs_id, name, canton, status, website, vendor, reachable, checked, checked_by, \
         notes FROM register",
    );
    only(&mut qb);
    qb.push(" ORDER BY canton, bfs_id");
    let rows: Vec<RegisterRow> = qb.build_query_as().fetch_all(pool).await?;
    let mut qb = QueryBuilder::new(
        "SELECT bfs_id, body, kind, status, listing_url, \"from\", \"to\", cadence, obstacle, how \
         FROM register_publications",
    );
    only(&mut qb);
    qb.push(" ORDER BY bfs_id, position");
    let publications: Vec<Publication> = qb.build_query_as().fetch_all(pool).await?;
    let mut by_commune: HashMap<i64, Vec<Publication>> = HashMap::new();
    for p in publications {
        by_commune.entry(p.bfs_id).or_default().push(p);
    }
    Ok(rows
        .into_iter()
        .map(|r| {
            let publications = by_commune.remove(&r.bfs_id).unwrap_or_default();
            RegisterEntry::new(r, publications)
        })
        .collect())
}
