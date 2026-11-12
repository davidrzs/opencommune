//! Votes and finances from the dataset SQLite. Its columns are typed loosely by the dataset
//! build, so rows go to JSON with SQLite's own value types.

use std::collections::{BTreeMap, HashMap};

use serde_json::{Map, Value, json};
use sqlx::sqlite::SqliteRow;
use sqlx::{Column, Row, SqlitePool, TypeInfo, ValueRef};

/// Commune sizes for turnout by size: [min, max) inhabitants.
const SIZES: [(i64, Option<i64>); 6] = [
    (0, Some(1000)),
    (1000, Some(2000)),
    (2000, Some(5000)),
    (5000, Some(10000)),
    (10000, Some(20000)),
    (20000, None),
];
/// The years the deficit shares cover.
const CORE: (i64, i64) = (2018, 2025);

fn row_json(row: &SqliteRow) -> Map<String, Value> {
    row.columns()
        .iter()
        .map(|col| {
            let i = col.ordinal();
            let value = match row.try_get_raw(i) {
                Ok(raw) if !raw.is_null() => match raw.type_info().name() {
                    "INTEGER" => row.try_get::<i64, _>(i).map_or(Value::Null, Value::from),
                    "REAL" => row.try_get::<f64, _>(i).map_or(Value::Null, Value::from),
                    "TEXT" => row.try_get::<String, _>(i).map_or(Value::Null, Value::from),
                    _ => Value::Null,
                },
                _ => Value::Null,
            };
            (col.name().to_string(), value)
        })
        .collect()
}

async fn rows(
    pool: &SqlitePool,
    sql: &'static str,
    bind: Option<i64>,
) -> sqlx::Result<Vec<Map<String, Value>>> {
    let mut query = sqlx::query(sql);
    if let Some(b) = bind {
        query = query.bind(b);
    }
    Ok(query.fetch_all(pool).await?.iter().map(row_json).collect())
}

/// Python's `statistics.median`.
fn median(mut values: Vec<f64>) -> Option<f64> {
    if values.is_empty() {
        return None;
    }
    values.sort_by(f64::total_cmp);
    let n = values.len();
    Some(if n % 2 == 1 {
        values[n / 2]
    } else {
        (values[n / 2 - 1] + values[n / 2]) / 2.0
    })
}

/// Python truthiness of a JSON number or string.
fn truthy(v: Option<&Value>) -> bool {
    match v {
        Some(Value::Number(n)) => n.as_f64().is_some_and(|x| x != 0.0),
        Some(Value::String(s)) => !s.is_empty(),
        Some(Value::Bool(b)) => *b,
        _ => false,
    }
}

/// Formal agenda items that tell a reader nothing about what the commune decided:
/// `dataset.FORMAL`, a case-insensitive regular expression, spelled out.
pub fn is_formal(title: &str) -> bool {
    const WORDS: [&str; 13] = [
        "traktandenliste",
        "protokoll",
        "beschlussfähigkeit",
        "beschlussfahigkeit",
        "stimmenzähler",
        "stimmenzahler",
        "ordre du jour",
        "ordine del giorno",
        "verbale",
        "scrutateur",
        "scrutator",
        "procès",
        "proces",
    ];
    let t = title.to_lowercase();
    WORDS[..11].iter().any(|w| t.contains(w))
        // proc[eè]s.verbal: any one character but a line break between the two words
        || WORDS[11..].iter().any(|w| {
            t.match_indices(w).any(|(i, m)| {
                let mut rest = t[i + m.len()..].chars();
                rest.next().is_some_and(|c| c != '\n') && rest.as_str().starts_with("verbal")
            })
        })
}

/// `GET /api/dataset/communes/{bfs_id}`: meetings, votes and finance years of one commune.
pub async fn commune(pool: &SqlitePool, bfs_id: i64) -> sqlx::Result<Value> {
    let meetings = rows(
        pool,
        "select sha256, body, meeting_date, eligible_voters, attendees, turnout, \
         attendees_agree from assemblies where commune_bfs_id = ? order by meeting_date desc",
        Some(bfs_id),
    )
    .await?;
    let mut votes = rows(
        pool,
        "select v.sha256, a.meeting_date, a.body, v.position, v.motion, v.motion_kind, \
         v.title, v.title_withheld, v.category, v.outcome, v.vote_method, v.votes_yes, \
         v.votes_no, v.abstentions, v.amount_chf, v.counts_agree \
         from assembly_votes v join assemblies a using (sha256) \
         where a.commune_bfs_id = ? and not coalesce(v.possible_duplicate, 0) \
         order by a.meeting_date desc, v.position, v.motion",
        Some(bfs_id),
    )
    .await?;
    for v in &mut votes {
        let formal = v
            .get("title")
            .and_then(Value::as_str)
            .is_some_and(|t| !t.is_empty() && is_formal(t));
        v.insert("formal".into(), Value::Bool(formal));
    }
    let finance = rows(
        pool,
        "select fiscal_year, type, operating_result, operating_expenses, operating_revenue, \
         net_investments, self_financing, tax_rate_percent, result_agrees, source_url \
         from finance_panel where commune_bfs_id = ? order by fiscal_year",
        Some(bfs_id),
    )
    .await?;
    let turnouts: Vec<f64> = meetings
        .iter()
        .filter(|m| truthy(m.get("turnout")) && m.get("body") == Some(&json!("assembly")))
        .filter_map(|m| m["turnout"].as_f64())
        .collect();
    let decided: Vec<&Map<String, Value>> = votes
        .iter()
        .filter(|v| {
            matches!(
                v.get("outcome").and_then(Value::as_str),
                Some("approved" | "amended" | "rejected")
            )
        })
        .collect();
    let summary = json!({
        "meetings": meetings.len(),
        "median_turnout": median(turnouts),
        "counted": votes.iter().filter(|v| !v["votes_yes"].is_null()).count(),
        "decided": decided.len(),
        "rejected": decided.iter().filter(|v| v["outcome"] == "rejected").count(),
    });
    Ok(json!({
        "meetings": meetings,
        "votes": votes,
        "finance": finance,
        "summary": summary,
    }))
}

async fn population(pool: &SqlitePool) -> sqlx::Result<HashMap<i64, i64>> {
    let rows: Vec<(i64, Option<i64>)> = sqlx::query_as("select bfs_id, population from communes")
        .fetch_all(pool)
        .await?;
    Ok(rows.into_iter().map(|(b, p)| (b, p.unwrap_or(0))).collect())
}

/// `GET /api/dataset/coverage`: minutes, counted votes and finance years per commune.
pub async fn coverage(pool: &SqlitePool) -> sqlx::Result<Value> {
    #[derive(Default)]
    struct Held {
        minutes: i64,
        counted: i64,
        finance_years: i64,
    }
    let mut per: BTreeMap<i64, Held> = BTreeMap::new();
    let minutes: Vec<(i64, i64)> =
        sqlx::query_as("select commune_bfs_id, count(*) from assemblies group by 1")
            .fetch_all(pool)
            .await?;
    for (bfs, n) in minutes {
        per.entry(bfs).or_default().minutes = n;
    }
    let counted: Vec<(i64, i64)> = sqlx::query_as(
        "select a.commune_bfs_id, count(*) from assembly_votes v join assemblies a using (sha256) \
         where v.votes_yes is not null and not coalesce(v.possible_duplicate, 0) group by 1",
    )
    .fetch_all(pool)
    .await?;
    for (bfs, n) in counted {
        per.entry(bfs).or_default().counted = n;
    }
    let finance: Vec<(i64, i64)> = sqlx::query_as(
        "select commune_bfs_id, count(distinct fiscal_year) from finance_panel \
         where operating_result is not null group by 1",
    )
    .fetch_all(pool)
    .await?;
    for (bfs, n) in finance {
        per.entry(bfs).or_default().finance_years = n;
    }
    let population = population(pool).await?;
    let total: i64 = population.values().sum();
    let share = |ids: &mut dyn Iterator<Item = i64>| -> Option<f64> {
        let covered: i64 = ids.map(|b| population.get(&b).copied().unwrap_or(0)).sum();
        (total != 0).then(|| covered as f64 / total as f64)
    };
    let with_minutes = per.values().filter(|r| r.minutes != 0).count();
    let with_finance = per.values().filter(|r| r.finance_years != 0).count();
    Ok(json!({
        "communes": per.iter().map(|(bfs, r)| json!({
            "bfs_id": bfs,
            "minutes": r.minutes,
            "counted": r.counted,
            "finance_years": r.finance_years,
        })).collect::<Vec<_>>(),
        "totals": {
            "communes": per.len(),
            "communes_with_minutes": with_minutes,
            "communes_with_finance": with_finance,
            "population_share": share(&mut per.keys().copied()),
            "minutes": per.values().map(|r| r.minutes).sum::<i64>(),
            "counted": per.values().map(|r| r.counted).sum::<i64>(),
        },
    }))
}

/// `GET /api/dataset/findings`: deficit shares by year and median turnout by commune size.
pub async fn findings(pool: &SqlitePool) -> sqlx::Result<Value> {
    let deficits: Vec<Map<String, Value>> = sqlx::query(
        "select fiscal_year as year, type, sum(operating_result < 0) as deficit, \
         count(*) as n from finance_panel \
         where fiscal_year between ? and ? and operating_result is not null \
         and not coalesce(results_differ, 0) group by 1, 2 order by 1, 2",
    )
    .bind(CORE.0)
    .bind(CORE.1)
    .fetch_all(pool)
    .await?
    .iter()
    .map(row_json)
    .collect();
    let population = population(pool).await?;
    let turnouts: Vec<(i64, f64)> = sqlx::query_as(
        "select commune_bfs_id, turnout from assemblies where body = 'assembly' and turnout > 0",
    )
    .fetch_all(pool)
    .await?;
    let mut by_size: Vec<Vec<f64>> = vec![Vec::new(); SIZES.len()];
    for (bfs, t) in turnouts {
        let pop = population.get(&bfs).copied().unwrap_or(0);
        if let Some(i) = SIZES
            .iter()
            .position(|(lo, hi)| pop >= *lo && hi.is_none_or(|hi| pop < hi))
        {
            by_size[i].push(t);
        }
    }
    let turnout: Vec<Value> = SIZES
        .iter()
        .zip(by_size)
        .map(|((lo, hi), values)| {
            json!({"min": lo, "max": hi, "n": values.len(), "median": median(values)})
        })
        .collect();
    Ok(json!({"deficits": deficits, "turnout_by_size": turnout}))
}

#[cfg(test)]
mod tests {
    use super::{is_formal, median};

    #[test]
    fn formal_items_are_recognised() {
        assert!(is_formal("Genehmigung der Traktandenliste"));
        assert!(is_formal("Feststellung der Beschlussfähigkeit"));
        assert!(is_formal("Wahl der STIMMENZÄHLER"));
        assert!(is_formal("Approbation du procès-verbal"));
        assert!(is_formal("Nomina degli scrutatori"));
        assert!(is_formal("Élection des scrutateurs"));
        assert!(!is_formal("Kredit Schulhaus"));
        assert!(!is_formal("Procès verbaux")); // "procès verbaux": one character, then "verbau"
    }

    #[test]
    fn median_is_pythons() {
        assert_eq!(median(vec![]), None);
        assert_eq!(median(vec![0.1, 0.05]), Some(0.07500000000000001));
        assert_eq!(median(vec![3.0, 1.0, 2.0]), Some(2.0));
    }
}
