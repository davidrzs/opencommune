//! Communes, the register and the access observations.

use std::collections::HashMap;

use sqlx::{QueryBuilder, Sqlite, SqlitePool};

use crate::models::{
    BriefCommune, CantonCount, Commune, CommuneDetail, Publication, RegisterEntry, RegisterRow,
};

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

/// The MCP tool `list_communes` with a filter: the communes of `canton`, or whose name contains
/// `q` (`name_matches`), or both, by canton and name, with their number of documents and their
/// register status.
pub async fn brief(
    pool: &SqlitePool,
    canton: Option<&str>,
    q: Option<&str>,
) -> sqlx::Result<Vec<BriefCommune>> {
    let mut qb = QueryBuilder::new(
        "SELECT c.bfs_id, c.name, c.canton, c.language, \
         (SELECT count(*) FROM document_communes dc WHERE dc.bfs_id = c.bfs_id) AS documents, \
         r.status AS register_status \
         FROM communes c LEFT JOIN register r ON r.bfs_id = c.bfs_id WHERE 1",
    );
    if let Some(canton) = canton {
        qb.push(" AND c.canton = ")
            .push_bind(canton.to_ascii_uppercase());
    }
    qb.push(" ORDER BY c.canton, c.name");
    let rows: Vec<BriefCommune> = qb.build_query_as().fetch_all(pool).await?;
    Ok(match q {
        Some(q) => rows
            .into_iter()
            .filter(|c| name_matches(&c.name, q))
            .collect(),
        None => rows,
    })
}

/// The MCP tool `list_communes` without a filter: per canton, its communes and the documents they
/// link, a document linked by two of them counted once.
pub async fn per_canton(pool: &SqlitePool) -> sqlx::Result<Vec<CantonCount>> {
    sqlx::query_as(
        "SELECT c.canton, count(DISTINCT c.bfs_id) AS communes, \
         count(DISTINCT dc.sha256) AS documents \
         FROM communes c LEFT JOIN document_communes dc ON dc.bfs_id = c.bfs_id \
         GROUP BY c.canton ORDER BY c.canton",
    )
    .fetch_all(pool)
    .await
}

/// Whether a commune's name contains `q`, comparing letters and digits only, without case and
/// accents, with ä, ö and ü also read as ae, oe and ue: `zurich` and `zuerich` find Zürich,
/// `st stephan` finds St. Stephan. A `q` without a letter or a digit matches nothing.
pub fn name_matches(name: &str, q: &str) -> bool {
    let q = fold(q, false);
    !q.is_empty() && (fold(name, false).contains(&q) || fold(name, true).contains(&q))
}

/// Letters and digits in lower case without accents (spaces, punctuation and combining marks
/// left out); with `umlauts`, ä, ö and ü become ae, oe and ue.
fn fold(text: &str, umlauts: bool) -> String {
    let mut out = String::with_capacity(text.len());
    for c in text.chars().flat_map(char::to_lowercase) {
        match c {
            'ä' | 'ö' | 'ü' if umlauts => {
                out.push(match c {
                    'ä' => 'a',
                    'ö' => 'o',
                    _ => 'u',
                });
                out.push('e');
            }
            'à' | 'á' | 'â' | 'ã' | 'ä' | 'å' => out.push('a'),
            'ç' => out.push('c'),
            'è' | 'é' | 'ê' | 'ë' => out.push('e'),
            'ì' | 'í' | 'î' | 'ï' => out.push('i'),
            'ñ' => out.push('n'),
            'ò' | 'ó' | 'ô' | 'õ' | 'ö' => out.push('o'),
            'ù' | 'ú' | 'û' | 'ü' => out.push('u'),
            'ÿ' => out.push('y'),
            'œ' => out.push_str("oe"),
            'æ' => out.push_str("ae"),
            c if c.is_alphanumeric() => out.push(c),
            _ => {}
        }
    }
    out
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
        "SELECT d.year, s.family, count(DISTINCT d.sha256) AS documents, \
         sum(s.pages) AS pages, \
         count(DISTINCT CASE WHEN s.position = 1 THEN d.sha256 END) AS first_part_documents \
         FROM documents d \
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

#[cfg(test)]
mod tests {
    use super::name_matches;

    #[test]
    fn names_match_without_case_and_accents() {
        for q in ["Zürich", "zurich", "ZUERICH", "rich"] {
            assert!(name_matches("Zürich", q), "{q}");
        }
        assert!(name_matches("Zürich", "Zu\u{308}rich")); // a decomposed ü
        assert!(name_matches("Genève", "geneve"));
        assert!(name_matches("Delémont", "DELEMONT"));
        assert!(name_matches("Biel/Bienne", "bienne"));
        // punctuation and spaces do not count
        assert!(name_matches("St. Stephan", "St Stephan"));
        assert!(name_matches("Wangen-Brüttisellen", "wangen bruettisellen"));
        assert!(name_matches("Wangen-Brüttisellen", "Wangen Brüttisellen"));
        assert!(name_matches("L'Isle", "L’Isle"));
        assert!(name_matches("Rickenbach (ZH)", "rickenbach zh"));
        assert!(name_matches("Wil (SG)", " wil "));
        assert!(!name_matches("Bern", "basel"));
        assert!(!name_matches("Bern", "-")); // no letter: nothing, not everything
    }
}
