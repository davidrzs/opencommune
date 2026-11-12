//! Communes, their holdings, the register and access observations (`search.list_communes`,
//! `search.list_register`, `catalog.coverage`, `crawl/access.enrich`).

use std::collections::HashMap;

use sqlx::{AssertSqlSafe, SqlitePool};

use crate::models::{
    Access, ArchiveCommune, Commune, CommuneRow, Holding, HoldingRow, Publication, RegisterEntry,
    RegisterRow, SlimAccess, SlimCommune, SlimRow,
};

const COMMUNE_SELECT: &str = "SELECT c.bfs_id, c.name, c.canton, c.language, c.website, \
    c.vendor, c.minutes_url, c.publicity_regime, c.last_crawled, c.lat, c.lon, \
    count(DISTINCT doc.id) AS documents, count(d.rid) AS decisions, \
    r.status AS register_status, r.note AS register_note \
    FROM communes c LEFT JOIN documents doc ON doc.commune_bfs_id = c.bfs_id \
    LEFT JOIN decisions d ON d.document_id = doc.id \
    LEFT JOIN register r ON r.bfs_id = c.bfs_id";

const HOLDING_SELECT: &str = "SELECT commune_bfs_id, body, kinds, documents, undated, parsed, \
    extracted, records, decisions, first_date, last_date, per_year, expected_interval_days, gaps, \
    stale, listed_not_held, last_crawl, last_result, health, register_status, register_note, \
    available_from FROM holdings";

/// An observation older than a week is shown as stale (`crawl/access.enrich`).
const ACCESS_SELECT: &str = "SELECT bfs_id, status, checked_at, robots_url, restricted_at, \
    source_url, julianday('now') - julianday(coalesce(restricted_at, checked_at)) >= 7 AS stale \
    FROM access_observations";

/// `search.list_communes`: every commune of the archive, by canton and name.
pub async fn list(pool: &SqlitePool) -> sqlx::Result<Vec<Commune>> {
    let rows: Vec<CommuneRow> = sqlx::query_as(AssertSqlSafe(format!(
        "{COMMUNE_SELECT} GROUP BY c.bfs_id ORDER BY c.canton, c.name"
    )))
    .fetch_all(pool)
    .await?;
    let held: Vec<HoldingRow> = sqlx::query_as(AssertSqlSafe(format!(
        "{HOLDING_SELECT} ORDER BY commune_bfs_id, body"
    )))
    .fetch_all(pool)
    .await?;
    let mut holdings: HashMap<i64, Vec<Holding>> = HashMap::new();
    for h in held {
        holdings.entry(h.commune_bfs_id).or_default().push(h.into());
    }
    Ok(rows
        .into_iter()
        .map(|c| {
            let mine = holdings.remove(&c.bfs_id).unwrap_or_default();
            Commune::new(c, mine)
        })
        .collect())
}

/// The commune page: the archive row with the catalogue count and the access observations.
pub async fn detail(pool: &SqlitePool, bfs_id: i64) -> sqlx::Result<Option<ArchiveCommune>> {
    let access: Vec<Access> = sqlx::query_as(AssertSqlSafe(format!(
        "{ACCESS_SELECT} WHERE bfs_id = ? ORDER BY checked_at DESC"
    )))
    .bind(bfs_id)
    .fetch_all(pool)
    .await?;
    let row: Option<CommuneRow> = sqlx::query_as(AssertSqlSafe(format!(
        "{COMMUNE_SELECT} WHERE c.bfs_id = ? GROUP BY c.bfs_id"
    )))
    .bind(bfs_id)
    .fetch_optional(pool)
    .await?;
    let Some(mut row) = row else {
        let entry: Option<(i64, String, String, Option<String>)> =
            sqlx::query_as("SELECT bfs_id, name, canton, website FROM register WHERE bfs_id = ?")
                .bind(bfs_id)
                .fetch_optional(pool)
                .await?;
        return Ok(entry.map(
            |(bfs_id, name, canton, website)| ArchiveCommune::RegisterOnly {
                bfs_id,
                name,
                canton,
                website,
                documents: 0,
                decisions: 0,
                holdings: Vec::new(),
                access,
            },
        ));
    };
    let holdings: Vec<HoldingRow> = sqlx::query_as(AssertSqlSafe(format!(
        "{HOLDING_SELECT} WHERE commune_bfs_id = ? ORDER BY body"
    )))
    .bind(bfs_id)
    .fetch_all(pool)
    .await?;
    let holdings: Vec<Holding> = holdings.into_iter().map(Holding::from).collect();
    let (any_catalogue, catalogue): (bool, i64) = sqlx::query_as(
        "SELECT EXISTS (SELECT 1 FROM pdf_catalog), \
         (SELECT count(*) FROM pdf_catalog WHERE commune_bfs_id = ?)",
    )
    .bind(bfs_id)
    .fetch_one(pool)
    .await?;
    row.documents = archive_documents(
        any_catalogue,
        catalogue,
        (!holdings.is_empty()).then(|| holdings.iter().map(|h| h.documents).sum()),
        row.documents,
    );
    Ok(Some(ArchiveCommune::Covered {
        commune: Commune::new(row, holdings),
        access,
    }))
}

/// `catalog.coverage`: the catalogue's count once there is a catalogue, else what the holdings
/// or the published documents give.
fn archive_documents(any_catalogue: bool, catalogue: i64, held: Option<i64>, docs: i64) -> i64 {
    if any_catalogue {
        catalogue
    } else {
        held.unwrap_or(docs)
    }
}

/// The map and the commune list: every commune of the archive and of the register with the
/// fields the front end shows.
pub async fn slim(pool: &SqlitePool) -> sqlx::Result<Vec<SlimCommune>> {
    let rows: Vec<SlimRow> = sqlx::query_as(
        "SELECT c.bfs_id, c.name, c.canton, c.lat, c.lon, \
         (SELECT count(*) FROM documents doc WHERE doc.commune_bfs_id = c.bfs_id) AS documents, \
         (SELECT count(*) FROM documents doc JOIN decisions d ON d.document_id = doc.id \
          WHERE doc.commune_bfs_id = c.bfs_id) AS decisions, \
         (SELECT count(*) FROM pdf_catalog p WHERE p.commune_bfs_id = c.bfs_id) AS catalogue, \
         (SELECT sum(h.documents) FROM holdings h WHERE h.commune_bfs_id = c.bfs_id) AS held \
         FROM communes c \
         UNION ALL \
         SELECT r.bfs_id, r.name, r.canton, NULL, NULL, 0, 0, 0, NULL FROM register r \
         WHERE r.bfs_id NOT IN (SELECT bfs_id FROM communes)",
    )
    .fetch_all(pool)
    .await?;
    let any_catalogue: bool = sqlx::query_scalar("SELECT EXISTS (SELECT 1 FROM pdf_catalog)")
        .fetch_one(pool)
        .await?;
    let observed: Vec<SlimAccess> = sqlx::query_as(
        "SELECT bfs_id, status, \
         julianday('now') - julianday(coalesce(restricted_at, checked_at)) >= 7 AS stale, \
         restricted_at FROM access_observations ORDER BY bfs_id, checked_at DESC",
    )
    .fetch_all(pool)
    .await?;
    let mut access: HashMap<i64, Vec<SlimAccess>> = HashMap::new();
    for a in observed {
        access.entry(a.bfs_id).or_default().push(a);
    }
    Ok(rows
        .into_iter()
        .map(|r| SlimCommune {
            documents: archive_documents(any_catalogue, r.catalogue, r.held, r.documents),
            access: access.remove(&r.bfs_id).unwrap_or_default(),
            bfs_id: r.bfs_id,
            name: r.name,
            canton: r.canton,
            lat: r.lat,
            lon: r.lon,
            decisions: r.decisions,
        })
        .collect())
}

/// `search.list_register`: every commune of the register with its publications.
pub async fn register(pool: &SqlitePool) -> sqlx::Result<Vec<RegisterEntry>> {
    let entries: Vec<RegisterRow> = sqlx::query_as(
        "SELECT bfs_id, name, canton, status, website, vendor, reachable, checked, checked_by, \
         notes FROM register ORDER BY canton, bfs_id",
    )
    .fetch_all(pool)
    .await?;
    let publications: Vec<Publication> = sqlx::query_as(
        "SELECT bfs_id, body, kind, status, listing_url, \"from\", \"to\", cadence, obstacle, how \
         FROM register_publications ORDER BY bfs_id, position",
    )
    .fetch_all(pool)
    .await?;
    let mut by_commune: HashMap<i64, Vec<Publication>> = HashMap::new();
    for p in publications {
        by_commune.entry(p.bfs_id).or_default().push(p);
    }
    Ok(entries
        .into_iter()
        .map(|e| {
            let pubs = by_commune.remove(&e.bfs_id).unwrap_or_default();
            RegisterEntry::new(e, pubs)
        })
        .collect())
}
