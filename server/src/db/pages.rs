//! What the crawler-facing pages read: the archive's totals, the communes with decisions, the
//! sitemap's addresses and a commune page's facts.

use sqlx::SqlitePool;

use crate::db::{communes, decisions};
use crate::models::{ArchiveCommune, CommuneDecisions, Decision, PageTotals};

/// Decisions and catalogue documents, each with the number of communes they come from.
pub async fn totals(pool: &SqlitePool) -> sqlx::Result<PageTotals> {
    sqlx::query_as(
        "SELECT (SELECT count(*) FROM decisions) AS decisions, \
         (SELECT count(DISTINCT commune_bfs_id) FROM decisions) AS decision_communes, \
         (SELECT count(*) FROM pdf_catalog) AS documents, \
         (SELECT count(DISTINCT commune_bfs_id) FROM pdf_catalog) AS document_communes",
    )
    .fetch_one(pool)
    .await
}

/// Communes with at least one decision, by name.
pub async fn communes_with_decisions(pool: &SqlitePool) -> sqlx::Result<Vec<CommuneDecisions>> {
    sqlx::query_as(
        "SELECT c.bfs_id, c.name, c.canton, count(*) AS decisions \
         FROM decisions d JOIN communes c ON c.bfs_id = d.commune_bfs_id \
         GROUP BY c.bfs_id ORDER BY c.name",
    )
    .fetch_all(pool)
    .await
}

/// The sitemap's pages: communes with documents or decisions, and every decision.
pub async fn sitemap(pool: &SqlitePool) -> sqlx::Result<(Vec<i64>, Vec<String>)> {
    let communes = sqlx::query_scalar(
        "SELECT commune_bfs_id FROM pdf_catalog UNION SELECT commune_bfs_id FROM documents \
         ORDER BY 1",
    )
    .fetch_all(pool)
    .await?;
    let decisions = sqlx::query_scalar("SELECT id FROM decisions ORDER BY meeting_date DESC, id")
        .fetch_all(pool)
        .await?;
    Ok((communes, decisions))
}

/// A commune with its twenty newest decisions; None when neither the archive nor the register
/// knows it.
pub async fn commune(
    pool: &SqlitePool,
    bfs_id: i64,
) -> sqlx::Result<Option<(ArchiveCommune, Vec<Decision>)>> {
    let Some(commune) = communes::detail(pool, bfs_id).await? else {
        return Ok(None);
    };
    let recent = decisions::search(
        pool,
        &decisions::SearchFilters {
            q: None,
            commune: Some(bfs_id),
            canton: None,
            category: None,
            outcome: None,
            lang: None,
            body: None,
            date_from: None,
            date_to: None,
            min_amount: None,
            limit: 20,
            offset: 0,
        },
    )
    .await?;
    Ok(Some((commune, recent.items)))
}
