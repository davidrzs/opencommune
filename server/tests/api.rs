//! The whole server against small fixture databases created here: the archive schema as the
//! Python package creates it (`fixtures/archive.sql`) plus the serving tables
//! (`src/opencommune/serving.sql`).

use std::net::SocketAddr;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::time::Duration;

use axum::Router;
use axum::body::{Body, to_bytes};
use axum::extract::ConnectInfo;
use axum::http::{Request, StatusCode, header};
use opencommune_server::site::Site;
use opencommune_server::usage::Usage;
use opencommune_server::{AppState, app, db};
use serde_json::{Value, json};
use sqlx::sqlite::{SqliteConnectOptions, SqlitePool};
use tower::ServiceExt;

const ARCHIVE: &str = include_str!("fixtures/archive.sql");
const SERVING: &str = include_str!("../../src/opencommune/serving.sql");

const ROWS: &str = r#"
INSERT INTO communes VALUES
  (261, 'Zürich', 'ZH', 'de', 'https://www.stadt-zuerich.ch', 'custom', NULL, NULL,
   '2026-09-01 10:00:00.000000', 47.37, 8.54),
  (5938, 'Yverdon-les-Bains', 'VD', 'fr', 'https://www.yverdon.ch', NULL, NULL, NULL, NULL,
   46.78, 6.64);
INSERT INTO documents VALUES
  ('doc-zh', 261, 'assembly', 'https://www.stadt-zuerich.ch/p.pdf', 'aaaa', '2026-09-06 19:55:27.169245',
   '2024-06-12', 'de', 12, 0, 'Gemeindeversammlung 2024', 0, 'html_links'),
  ('doc-vd', 5938, 'parliament', 'https://www.yverdon.ch/pv.pdf', 'bbbb', '2026-09-06 19:55:41.000000',
   '2025-09-03', 'fr', 30, 1, 'Conseil communal', 2, 'html_links');
INSERT INTO decisions (id, document_id, commune_bfs_id, meeting_date, agenda_no, title, category,
  sensitive_topic, summary, outcome, votes_for, votes_against, amount_chf, refs, office_holders,
  page_start, page_end, confidence, contains_private_individuals, redaction_applied,
  extraction_model, extraction_version, language) VALUES
  ('dec-zh', 'doc-zh', 261, '2024-06-12', '3', 'Kredit für das Schulhaus', 'finance_credit', 'none',
   'Die Versammlung bewilligt den Kredit.', 'approved', 50, 10, 2400000.0, '["Art. 1 GO"]', '[]',
   4, 5, 0.9, 0, 0, 'model-a', '1', 'de'),
  ('dec-vd', 'doc-vd', 5938, '2025-09-03', NULL, 'Crédit pour l''École', 'school', 'none',
   'Le conseil accepte le crédit.', NULL, NULL, NULL, NULL, 'null', '["Syndic"]',
   7, 7, NULL, 0, 1, 'model-b', '1', 'fr');
INSERT INTO holdings VALUES
  (261, 'assembly', '["minutes"]', 9, 4, 9, 9, 9, 1, '2018-01-01', '2021-12-31', '{"2018": 2}',
   91.3, '[]', 0, 0, '2026-10-01 08:00:00.123000', 'ok', 'ok', 'configured', NULL, '2018',
   '2026-10-01 08:00:00.000000'),
  (261, 'parliament', '[]', 0, 0, 0, 0, 0, 0, NULL, NULL, '{}', NULL, '[]', 0, 0,
   '2026-10-02 09:00:00.000000', 'ok', 'empty', NULL, NULL, NULL, '2026-10-02 09:00:00.000000');
INSERT INTO pdf_catalog VALUES
  ('aaaa', 261, 'Zürich', 'ZH', 'assembly', '2024-06-12', 'day', 'Gemeindeversammlung 2024',
   'https://www.stadt-zuerich.ch/p.pdf', 'html_links', 'published', 1,
   '2026-10-23 00:49:06.430902'),
  ('cccc', 261, 'Zürich', 'ZH', 'assembly', '2019-05-01', 'month', 'Protokoll 2019',
   'https://www.stadt-zuerich.ch/Protokoll Mai 2019.pdf', 'html_links', 'pending_parse', 0,
   '2026-10-23 00:49:06.430902'),
  ('dddd', 261, 'Zürich', 'ZH', 'executive', NULL, 'day', 'Gemeindedokument',
   'ftp://old.example/x.pdf', 'html_links', 'pending_parse', 0, '2026-10-23 00:49:06.430902');
INSERT INTO register VALUES
  (261, 'Zürich', 'ZH', 'configured', 'https://www.stadt-zuerich.ch', 'custom', 1, '2026-09-30',
   'reviewer', NULL, NULL),
  (4176, 'Schwaderloch', 'AG', 'not_examined', 'http://www.schwaderloch.ch', NULL, NULL, NULL, NULL,
   NULL, NULL),
  (1, 'Aeugst am Albis', 'ZH', 'blocked_robots', 'https://www.aeugst-albis.ch', 'i-web', 0,
   '2026-10-01', 'reviewer', 'robots.txt disallows the archive', 'robots.txt disallows the archive');
INSERT INTO register_publications VALUES
  (261, 0, 'parliament', 'minutes', 'configured', 'https://www.gemeinderat-zuerich.ch/protokolle',
   '2018', NULL, '50 per year', NULL, NULL),
  (261, 1, 'executive', 'decisions', 'not_published', NULL, NULL, NULL, NULL, 'not public', NULL);
INSERT INTO access_observations VALUES
  (261, 'https://archiv.stadt-zuerich.ch/', 'rate_limited',
   strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now', '-10 days'), 'https://archiv.stadt-zuerich.ch/robots.txt', NULL),
  (261, 'https://www.stadt-zuerich.ch/', 'restricted',
   strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now', '-1 day'), 'https://www.stadt-zuerich.ch/robots.txt',
   strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now', '-1 day')),
  (4176, 'http://www.schwaderloch.ch/', 'technical_error',
   strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now', '-2 days'), 'http://www.schwaderloch.ch/robots.txt', NULL),
  (5938, 'https://www.example.ch/', 'technical_error',
   strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now', '-1 day'), 'https://www.example.ch/robots.txt',
   strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now', '-20 days'));
"#;

/// A small dataset fixture.
const DATASET: &str = r#"
create table communes (bfs_id integer primary key, name text, canton text, population integer);
create table assemblies (sha256 text primary key, commune_bfs_id integer, body text,
    meeting_date text, eligible_voters integer, attendees integer, turnout real,
    attendees_agree integer);
create table assembly_votes (sha256 text, position integer, motion integer, motion_kind text,
    title text, title_withheld integer, category text, outcome text, vote_method text,
    votes_yes integer, votes_no integer, abstentions integer, amount_chf real,
    counts_agree integer, possible_duplicate integer);
create table finance_panel (commune_bfs_id integer, fiscal_year integer, type text,
    operating_result real, operating_expenses real, operating_revenue real, net_investments real,
    self_financing real, tax_rate_percent real, result_agrees integer, results_differ integer,
    source_url text);
insert into communes values (1, 'Testdorf', 'BE', 800), (2, 'Grossstadt', 'ZH', 50000);
insert into assemblies values ('a', 1, 'assembly', '2024-06-12', 600, 60, 0.1, 1),
    ('b', 1, 'assembly', '2023-12-04', 600, 30, 0.05, 1);
insert into assembly_votes values
    ('a', 1, 0, null, 'Genehmigung der Traktandenliste', 0, 'other', 'approved',
     'unanimous', null, null, null, null, null, 0),
    ('a', 2, 0, null, 'Kredit Schulhaus', 0, 'finance_credit', 'approved', 'counted',
     50, 10, 0, 2400000, 1, 0),
    ('a', 3, 0, null, 'Kredit Schulhaus', 0, 'finance_credit', 'approved', 'counted',
     50, 10, 0, 2400000, 1, 1),
    ('a', 4, 0, null, null, 1, 'naturalization', 'approved', 'open_majority',
     null, null, null, null, null, 0),
    ('b', 1, 0, null, 'Budget 2024', 0, 'finance_budget', 'rejected', 'counted',
     12, 18, 0, null, 0, 0);
insert into finance_panel values
    (1, 2024, 'budget', -100000, 5000000, 4900000, 300000, 200000, 112, 1, 0,
     'https://example.ch/budget.pdf'),
    (1, 2024, 'accounts', 50000, 4900000, 4950000, 250000, 300000, 112, 0, 0,
     'https://example.ch/rechnung.pdf');
"#;

fn temp_path(name: &str) -> PathBuf {
    static N: AtomicUsize = AtomicUsize::new(0);
    let n = N.fetch_add(1, Ordering::Relaxed);
    std::env::temp_dir().join(format!(
        "opencommune-server-test-{}-{n}-{name}",
        std::process::id()
    ))
}

async fn create(path: &Path, sql: &[&'static str]) {
    let options = SqliteConnectOptions::new()
        .filename(path)
        .create_if_missing(true);
    let pool = SqlitePool::connect_with(options).await.unwrap();
    for s in sql {
        sqlx::raw_sql(*s).execute(&pool).await.unwrap();
    }
    pool.close().await;
}

struct Fixture {
    router: Router,
    usage_path: PathBuf,
    static_dir: PathBuf,
    files: Vec<PathBuf>,
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.static_dir);
        for f in &self.files {
            for suffix in ["", "-wal", "-shm", "-journal"] {
                let _ = std::fs::remove_file(format!("{}{suffix}", f.display()));
            }
        }
    }
}

async fn fixture(with_dataset: bool, with_usage: bool) -> Fixture {
    build(with_dataset, with_usage, false).await
}

/// The front end's page shell as the build writes it, reduced to what the server touches.
const SHELL: &str = "<!doctype html><html lang=\"de\"><head><meta charset=\"utf-8\"></head>\
<body data-sveltekit-preload-data=\"hover\"><div style=\"display: contents\"></div></body></html>";

async fn build(with_dataset: bool, with_usage: bool, indexing: bool) -> Fixture {
    let archive = temp_path("archive.db");
    create(&archive, &[ARCHIVE, SERVING, ROWS]).await;
    let dataset_path = temp_path("dataset.db");
    let dataset = if with_dataset {
        let path = dataset_path.clone();
        create(&path, &[DATASET]).await;
        Some(db::open_read_only(&path).await.unwrap())
    } else {
        None
    };
    let usage_path = temp_path("usage.sqlite3");
    let usage = if with_usage {
        Some(Usage::open(&usage_path, true).await.unwrap())
    } else {
        None
    };
    let static_dir = temp_path("static");
    std::fs::create_dir_all(static_dir.join("_app/immutable")).unwrap();
    std::fs::write(static_dir.join("index.html"), SHELL).unwrap();
    std::fs::write(static_dir.join("_app/immutable/app.js"), "console.log(1)").unwrap();
    let state = AppState {
        db: db::open_read_only(&archive).await.unwrap(),
        dataset,
        usage,
        site: Site::new("https://example.test", indexing, &static_dir),
    };
    let router = app(state, &static_dir, &["localhost".to_string()]);
    Fixture {
        files: vec![archive, dataset_path, usage_path.clone()],
        router,
        usage_path,
        static_dir,
    }
}

async fn send(router: &Router, request: Request<Body>) -> (StatusCode, header::HeaderMap, Vec<u8>) {
    let response = router.clone().oneshot(request).await.unwrap();
    let status = response.status();
    let headers = response.headers().clone();
    let body = to_bytes(response.into_body(), usize::MAX).await.unwrap();
    (status, headers, body.to_vec())
}

async fn get(router: &Router, uri: &str) -> (StatusCode, Value) {
    let request = Request::get(uri).body(Body::empty()).unwrap();
    let (status, _, body) = send(router, request).await;
    (status, serde_json::from_slice(&body).unwrap_or(Value::Null))
}

#[tokio::test]
async fn full_text_search_ignores_diacritics_and_falls_back_to_like() {
    let f = fixture(false, false).await;
    let (status, page) = get(&f.router, "/api/decisions?q=ecole").await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(page["mode"], "fts");
    assert_eq!(page["total"], 1);
    assert_eq!(page["items"][0]["title"], "Crédit pour l'École");
    let (_, page) = get(&f.router, "/api/decisions?q=Schulh").await;
    assert_eq!(
        (page["mode"].as_str(), page["total"].as_i64()),
        (Some("fts"), Some(1))
    );
    let (_, page) = get(&f.router, "/api/decisions?q=bewilligt%20den").await;
    assert_eq!(page["mode"], "fts");
    let (_, page) = get(&f.router, "/api/decisions?q=xy").await;
    assert_eq!(
        (page["mode"].as_str(), page["total"].as_i64()),
        (Some("like"), Some(0))
    );
    let (_, page) = get(&f.router, "/api/decisions?q=rlich").await;
    assert_eq!(page["mode"], "like"); // no token starts with it, a substring match finds nothing
    let (_, page) = get(&f.router, "/api/decisions").await;
    assert_eq!(page["mode"], "recent");
    let ids: Vec<&str> = page["items"]
        .as_array()
        .unwrap()
        .iter()
        .map(|d| d["id"].as_str().unwrap())
        .collect();
    assert_eq!(ids, ["dec-vd", "dec-zh"]); // newest meeting first
    let (_, page) = get(&f.router, "/api/decisions?canton=zh&min_amount=1000").await;
    assert_eq!(page["total"], 1);
    let (status, _) = get(&f.router, "/api/decisions?limit=500").await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    let (status, _) = get(&f.router, "/api/decisions?from=2024-02-30").await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
}

#[tokio::test]
async fn a_decision_links_the_communes_original() {
    let f = fixture(false, false).await;
    let (status, d) = get(&f.router, "/api/decisions/dec-zh").await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(
        d["source_link"],
        "https://www.stadt-zuerich.ch/p.pdf#page=4"
    );
    assert!(d.get("copy_link").is_none() && d.get("local_pdf").is_none());
    assert_eq!(d["references"], json!(["Art. 1 GO"]));
    assert_eq!(
        d["commune"],
        json!({"bfs_id": 261, "name": "Zürich", "canton": "ZH"})
    );
    let (_, d) = get(&f.router, "/api/decisions/dec-vd").await;
    assert_eq!(d["references"], json!([])); // JSON null is an empty list
    assert_eq!(d["redaction_applied"], true);
    let (status, body) = get(&f.router, "/api/decisions/nope").await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    assert_eq!(body, json!({"detail": "decision not found"}));
}

#[tokio::test]
async fn communes_carry_holdings_and_the_register_status() {
    let f = fixture(false, false).await;
    let (_, list) = get(&f.router, "/api/communes").await;
    let list = list.as_array().unwrap();
    assert_eq!(list.len(), 2);
    assert_eq!(list[0]["bfs_id"], 5938); // VD before ZH
    let zh = &list[1];
    assert_eq!(zh["documents"], 1);
    assert_eq!(zh["decisions"], 1);
    assert_eq!(zh["last_crawled"], "2026-10-02T09:00:00"); // the newest crawl of any body
    assert_eq!(zh["register_status"], "configured");
    let assembly = &zh["holdings"][0];
    assert_eq!(assembly["per_year_average"], 1.2); // 5 dated documents over 4 years, half to even
    assert_eq!(assembly["last_crawl"], "2026-10-01T08:00:00.123000");
    assert_eq!(assembly["per_year"], json!({"2018": 2}));
    assert_eq!(zh["holdings"][1]["per_year_average"], Value::Null);
    assert_eq!(list[0]["last_crawled"], Value::Null);
    assert_eq!(list[0]["register_status"], Value::Null);
}

#[tokio::test]
async fn the_map_list_is_slim_and_includes_register_only_communes() {
    let f = fixture(false, false).await;
    let (status, list) = get(&f.router, "/api/archive/communes").await;
    assert_eq!(status, StatusCode::OK);
    let by_id = |id: i64| {
        list.as_array()
            .unwrap()
            .iter()
            .find(|c| c["bfs_id"] == id)
            .unwrap()
            .clone()
    };
    assert_eq!(list.as_array().unwrap().len(), 4);
    let zh = by_id(261);
    assert_eq!(zh["documents"], 3); // the catalogue's count
    assert_eq!(by_id(5938)["documents"], 0); // a catalogue exists, this commune has none in it
    // one access state per commune, never the observations themselves
    assert_eq!(zh["access"], "restricted");
    assert_eq!(by_id(5938)["access"], "earlier");
    assert_eq!(by_id(4176)["access"], "temporary");
    assert!(by_id(1).get("access").is_none());
    let keys: Vec<&String> = zh.as_object().unwrap().keys().collect();
    assert_eq!(
        keys,
        [
            "bfs_id",
            "name",
            "canton",
            "lat",
            "lon",
            "documents",
            "decisions",
            "access"
        ]
    );
    assert_eq!(by_id(1)["lat"], Value::Null);
}

#[tokio::test]
async fn the_commune_page_gets_its_own_detail() {
    let f = fixture(false, false).await;
    let (_, zh) = get(&f.router, "/api/archive/communes/261").await;
    assert_eq!(zh["website"], "https://www.stadt-zuerich.ch");
    assert_eq!(zh["documents"], 3);
    assert_eq!(
        zh["access"][0]["source_url"],
        "https://www.stadt-zuerich.ch/"
    );
    assert_eq!(zh["access"][1]["stale"], true);
    assert_eq!(zh["holdings"].as_array().unwrap().len(), 2);
    let (_, only) = get(&f.router, "/api/archive/communes/4176").await;
    let keys: Vec<&String> = only.as_object().unwrap().keys().collect();
    assert_eq!(
        keys,
        [
            "bfs_id",
            "name",
            "canton",
            "website",
            "documents",
            "decisions",
            "holdings",
            "access"
        ]
    );
    let (status, body) = get(&f.router, "/api/archive/communes/999").await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    assert_eq!(body["detail"], "commune not found");
}

#[tokio::test]
async fn the_register_and_its_summary() {
    let f = fixture(false, false).await;
    let (_, register) = get(&f.router, "/api/register").await;
    let ids: Vec<i64> = register
        .as_array()
        .unwrap()
        .iter()
        .map(|e| e["bfs_id"].as_i64().unwrap())
        .collect();
    assert_eq!(ids, [4176, 1, 261]); // by canton, then BFS id
    let zh = &register[2];
    assert_eq!(zh["publications"][0]["from"], "2018");
    assert_eq!(zh["publications"][1]["kind"], "decisions");
    assert_eq!(zh["reachable"], true);
    assert_eq!(zh["checked"], "2026-09-30");
    let (_, stats) = get(&f.router, "/api/stats").await;
    assert_eq!(stats["communes_in_register"], 3);
    assert_eq!(stats["register"]["blocked"], 1);
    assert_eq!(stats["register"]["examined"], 2);
    assert_eq!(stats["register"]["reachable"], 1);
    assert_eq!(stats["register"]["unreachable"], 1);
    assert_eq!(stats["register"]["by_status"]["needs_feature"], 0);
    assert_eq!(stats["by_outcome"], json!({"None": 1, "approved": 1}));
    assert_eq!(stats["by_health"], json!({"empty": 1, "ok": 1}));
    assert_eq!(stats["approved_amount_chf"], 2400000.0);
    assert_eq!(stats["decisions_dropped_for_privacy"], 2);
}

#[tokio::test]
async fn catalogue_lists_link_through_this_site_only() {
    let f = fixture(false, false).await;
    let (_, page) = get(&f.router, "/api/archive/documents?commune=261").await;
    assert_eq!(page["total"], 3);
    assert_eq!(page["years"], json!([2024, 2019]));
    let urls: Vec<&Value> = page["items"]
        .as_array()
        .unwrap()
        .iter()
        .map(|i| &i["url"])
        .collect();
    assert_eq!(
        urls,
        [
            &json!("/original/aaaa"),
            &json!("/original/cccc"),
            &Value::Null
        ]
    );
    assert!(
        !String::from_utf8_lossy(&serde_json::to_vec(&page).unwrap()).contains("stadt-zuerich")
    );
    let (_, page) = get(&f.router, "/api/archive/documents?commune=261&q=PROTOKOLL").await;
    assert_eq!(page["total"], 1);
    let (_, page) = get(&f.router, "/api/archive/documents?commune=261&q=%25").await;
    assert_eq!(page["total"], 0); // % is a character, not a wildcard
    let (_, page) = get(&f.router, "/api/archive/documents?commune=261&year=2019").await;
    assert_eq!(page["items"][0]["id"], "cccc");
    let (status, _) = get(&f.router, "/api/archive/documents?year=1700").await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);

    let request = Request::get("/original/cccc").body(Body::empty()).unwrap();
    let (status, headers, _) = send(&f.router, request).await;
    assert_eq!(status, StatusCode::FOUND);
    assert_eq!(
        headers[header::LOCATION],
        "https://www.stadt-zuerich.ch/Protokoll%20Mai%202019.pdf"
    );
    assert_eq!(headers["x-robots-tag"], "noindex, nofollow");
    let (status, _) = get(&f.router, "/original/dddd").await; // not an http(s) URL
    assert_eq!(status, StatusCode::NOT_FOUND);
}

#[tokio::test]
async fn dataset_routes_answer_404_without_a_dataset() {
    let f = fixture(false, false).await;
    let (status, body) = get(&f.router, "/api/dataset/findings").await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    assert_eq!(body["detail"], "dataset not configured");
}

#[tokio::test]
async fn dataset_votes_coverage_and_findings() {
    let f = fixture(true, false).await;
    let (_, data) = get(&f.router, "/api/dataset/communes/1").await;
    let titles: Vec<&Value> = data["votes"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| &v["title"])
        .collect();
    assert_eq!(
        titles.iter().filter(|t| **t == "Kredit Schulhaus").count(),
        1
    ); // read twice: left out
    assert!(titles.contains(&&Value::Null)); // the naturalisation keeps no title
    assert_eq!(data["votes"][0]["formal"], true);
    assert_eq!(data["summary"]["rejected"], 1);
    assert_eq!(data["summary"]["counted"], 2);
    assert!((data["summary"]["median_turnout"].as_f64().unwrap() - 0.075).abs() < 1e-9);
    assert_eq!(data["finance"][0]["type"], "budget");
    assert_eq!(data["finance"][1]["result_agrees"], 0);
    assert_eq!(data["finance"][0]["operating_result"], -100000.0); // a REAL stays a float

    let (_, coverage) = get(&f.router, "/api/dataset/coverage").await;
    assert_eq!(
        coverage["communes"],
        json!([{"bfs_id": 1, "minutes": 2, "counted": 2, "finance_years": 1}])
    );
    assert!(
        (coverage["totals"]["population_share"].as_f64().unwrap() - 800.0 / 50800.0).abs() < 1e-9
    );

    let (_, findings) = get(&f.router, "/api/dataset/findings").await;
    let budget = findings["deficits"]
        .as_array()
        .unwrap()
        .iter()
        .find(|d| d["type"] == "budget")
        .unwrap();
    assert_eq!(
        (
            budget["year"].as_i64(),
            budget["deficit"].as_i64(),
            budget["n"].as_i64()
        ),
        (Some(2024), Some(1), Some(1))
    );
    assert_eq!(
        findings["turnout_by_size"][0],
        json!({"min": 0, "max": 1000, "n": 2, "median": 0.07500000000000001})
    );
}

async fn usage_rows(path: &Path, want: usize) -> Vec<(String, String, i64, i64, i64, i64)> {
    let pool = SqlitePool::connect_with(SqliteConnectOptions::new().filename(path))
        .await
        .unwrap();
    for _ in 0..50 {
        let rows: Vec<(String, String, i64, i64, i64, i64)> = sqlx::query_as(
            "SELECT channel, route, bot, status, sum(requests), sum(searches) FROM totals \
             GROUP BY 1, 2, 3, 4 ORDER BY 1, 2",
        )
        .fetch_all(&pool)
        .await
        .unwrap();
        if rows.iter().map(|r| r.4 as usize).sum::<usize>() >= want {
            return rows;
        }
        tokio::time::sleep(Duration::from_millis(40)).await;
    }
    panic!("usage rows not written");
}

#[tokio::test]
async fn usage_counts_route_templates_without_paths_or_addresses() {
    let f = fixture(false, true).await;
    let browser = "Mozilla/5.0 (X11; Linux x86_64) Firefox/140.0";
    let peer: SocketAddr = "127.0.0.1:40000".parse().unwrap();
    for (uri, dnt) in [
        ("/api/decisions?q=Kredit", false),
        ("/api/decisions?q=nichtsdergleichen", false),
        ("/de/gemeinden/261", false),
        ("/fr/gemeinden/5938", true),
        ("/_app/immutable/app.js", false),
        ("/no/such/page", false),
        ("/api/nothing-here", false),
    ] {
        let mut request = Request::get(uri)
            .header(header::USER_AGENT, browser)
            .header("x-forwarded-for", "203.0.113.7");
        if dnt {
            request = request.header("dnt", "1");
        }
        let mut request = request.body(Body::empty()).unwrap();
        request.extensions_mut().insert(ConnectInfo(peer));
        send(&f.router, request).await;
    }
    get(&f.router, "/api/stats").await; // no user agent: a bot
    let rows = usage_rows(&f.usage_path, 5).await;
    assert_eq!(
        rows,
        [
            ("api".into(), "/api/decisions".into(), 0, 200, 2, 2),
            ("api".into(), "/api/stats".into(), 1, 200, 1, 0),
            ("web".into(), "/gemeinden/{id}".into(), 0, 200, 2, 0),
        ]
    );
    let pool = SqlitePool::connect_with(SqliteConnectOptions::new().filename(&f.usage_path))
        .await
        .unwrap();
    let (empty, visitors): (i64, i64) = sqlx::query_as(
        "SELECT (SELECT sum(empty_searches) FROM totals), (SELECT count(*) FROM visitors)",
    )
    .fetch_one(&pool)
    .await
    .unwrap();
    assert_eq!(empty, 1);
    assert_eq!(visitors, 1); // the DNT request has no visitor identifier
    let dump: Vec<(String,)> = sqlx::query_as(
        "SELECT group_concat(day || route || channel) FROM totals UNION ALL SELECT group_concat(token) FROM visitors",
    )
    .fetch_all(&pool)
    .await
    .unwrap();
    let dump = format!("{dump:?}");
    for secret in ["Kredit", "261", "203.0.113", "127.0.0.1", "Mozilla"] {
        assert!(!dump.contains(secret), "{secret} stored");
    }
}

#[tokio::test]
async fn the_front_end_is_served_with_a_fallback_and_api_errors_stay_json() {
    let f = fixture(false, false).await;
    let request = Request::get("/gemeinden/261").body(Body::empty()).unwrap();
    let (status, headers, body) = send(&f.router, request).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(
        body,
        std::fs::read(f.static_dir.join("index.html")).unwrap()
    );
    assert_eq!(headers["x-robots-tag"], "noindex, nofollow");
    let request = Request::get("/_app/immutable/app.js")
        .body(Body::empty())
        .unwrap();
    let (status, headers, _) = send(&f.router, request).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(
        headers[header::CACHE_CONTROL],
        "public, max-age=31536000, immutable"
    );
    let (status, body) = get(&f.router, "/api/nothing-here").await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    assert_eq!(body, json!({"detail": "Not Found"}));
}

#[tokio::test]
async fn mcp_lists_the_three_tools_and_answers_a_search() {
    let f = fixture(false, false).await;
    let post = |body: Value| {
        Request::post("/mcp")
            .header(header::HOST, "localhost")
            .header(header::CONTENT_TYPE, "application/json")
            .header(header::ACCEPT, "application/json, text/event-stream")
            .header("mcp-protocol-version", "2025-06-18")
            .body(Body::from(body.to_string()))
            .unwrap()
    };
    let init = json!({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}});
    let (status, _, body) = send(&f.router, post(init)).await;
    assert_eq!(status, StatusCode::OK);
    let body: Value = serde_json::from_slice(&body).unwrap();
    assert_eq!(body["result"]["serverInfo"]["name"], "opencommune");
    let (_, _, body) = send(
        &f.router,
        post(json!({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})),
    )
    .await;
    let body: Value = serde_json::from_slice(&body).unwrap();
    let mut names: Vec<&str> = body["result"]["tools"]
        .as_array()
        .unwrap()
        .iter()
        .map(|t| t["name"].as_str().unwrap())
        .collect();
    names.sort();
    assert_eq!(names, ["get_decision", "list_communes", "search_decisions"]);
    for tool in body["result"]["tools"].as_array().unwrap() {
        assert!(tool["title"].is_string(), "{tool}");
        assert_eq!(tool["annotations"]["readOnlyHint"], true);
        assert_eq!(tool["annotations"]["destructiveHint"], false);
    }
    let call = json!({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
        "name": "search_decisions", "arguments": {"query": "ecole", "limit": 500}}});
    let (_, _, body) = send(&f.router, post(call)).await;
    let body: Value = serde_json::from_slice(&body).unwrap();
    assert_eq!(body["result"]["structuredContent"]["total"], 1);
    assert_eq!(
        body["result"]["structuredContent"]["items"][0]["id"],
        "dec-vd"
    );
    // another Host is refused (DNS rebinding guard)
    let mut request = post(json!({"jsonrpc": "2.0", "id": 4, "method": "tools/list"}));
    request
        .headers_mut()
        .insert(header::HOST, "evil.example".parse().unwrap());
    let (status, _, _) = send(&f.router, request).await;
    assert!(status.is_client_error());
}

async fn page(router: &Router, uri: &str) -> (StatusCode, header::HeaderMap, String) {
    let request = Request::get(uri).body(Body::empty()).unwrap();
    let (status, headers, body) = send(router, request).await;
    (status, headers, String::from_utf8(body).unwrap())
}

#[tokio::test]
async fn commune_pages_carry_their_facts_for_crawlers() {
    let f = fixture(false, false).await;
    let (status, headers, html) = page(&f.router, "/fr/gemeinden/261").await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(headers["x-robots-tag"], "noindex, nofollow"); // indexing is off by default
    assert!(html.starts_with("<!doctype html><html lang=\"fr\">"));
    assert!(html.contains("<title>Zürich — OpenCommune</title>"));
    assert!(
        html.contains("<link rel=\"canonical\" href=\"https://example.test/fr/gemeinden/261\">")
    );
    assert!(html.contains("hreflang=\"de\" href=\"https://example.test/de/gemeinden/261\""));
    assert!(html.contains("\"@type\":\"AdministrativeArea\""));
    // the fact sheet opens the body and links the commune's decisions
    let facts = html.split("<main id=\"oc-facts\">").nth(1).unwrap();
    assert!(html.contains("data-sveltekit-preload-data=\"hover\"><main id=\"oc-facts\">"));
    assert!(facts.starts_with("<h1>Zürich</h1>"));
    assert!(facts.contains("<a href=\"/fr/entscheide/dec-zh\">Kredit für das Schulhaus</a>"));
    // a newly deployed front end names new script files: the next page uses its shell at once
    let deployed = SHELL.replace("<head>", "<head><script src=\"/_app/new.js\"></script>");
    std::fs::write(f.static_dir.join("index.html"), deployed).unwrap();
    let (_, _, html) = page(&f.router, "/fr/gemeinden/261").await;
    assert!(html.contains("/_app/new.js"));
    for unknown in [
        "/de/gemeinden/999",
        "/de/gemeinden/abc",
        "/de/entscheide/nothing",
    ] {
        let (status, _, html) = page(&f.router, unknown).await;
        assert_eq!(status, StatusCode::NOT_FOUND, "{unknown}");
        assert!(html.contains("<meta name=\"robots\" content=\"noindex\">"));
    }
}

#[tokio::test]
async fn decision_start_about_and_search_pages() {
    let f = fixture(false, false).await;
    let (status, _, html) = page(&f.router, "/de/entscheide/dec-zh").await;
    assert_eq!(status, StatusCode::OK);
    assert!(html.contains("<h1>Kredit für das Schulhaus</h1>"));
    assert!(html.contains("<a href=\"/de/gemeinden/261\">Zürich (ZH)</a> · 12.06.2024"));
    assert!(html.contains("https://www.stadt-zuerich.ch/p.pdf#page="));
    let (_, _, html) = page(&f.router, "/it").await;
    assert!(html.contains("\"@type\":\"Dataset\""));
    assert!(html.contains("<a href=\"/it/gemeinden/261\">Zürich (ZH)</a>"));
    let (status, _, html) = page(&f.router, "/de/ueber-uns").await;
    assert_eq!(status, StatusCode::OK);
    assert!(html.contains("<h1>Über OpenCommune</h1>"));
    let (status, _, html) = page(&f.router, "/fr/datenschutz").await;
    assert_eq!(status, StatusCode::OK);
    assert!(html.contains("<h1>Protection des données</h1>"));
    let (_, _, html) = page(&f.router, "/de/suche").await;
    assert!(html.contains("<meta name=\"robots\" content=\"noindex\">"));
    let request = Request::get("/").body(Body::empty()).unwrap();
    let (status, headers, _) = send(&f.router, request).await;
    assert_eq!(status, StatusCode::TEMPORARY_REDIRECT);
    assert_eq!(headers[header::LOCATION], "/de");
}

#[tokio::test]
async fn robots_sitemap_and_llms_txt() {
    let f = fixture(false, false).await;
    let (status, headers, robots) = page(&f.router, "/robots.txt").await;
    assert_eq!(status, StatusCode::OK);
    assert!(
        headers[header::CONTENT_TYPE]
            .to_str()
            .unwrap()
            .starts_with("text/plain")
    );
    // training crawlers read nothing, everyone else reads the pages but not the API
    assert!(robots.contains("User-agent: GPTBot\nUser-agent: ClaudeBot\n"));
    assert!(robots.contains("Bytespider\nUser-agent: cohere-ai\nDisallow: /\n"));
    assert!(robots.contains("User-agent: *\nDisallow: /api/\n"));
    assert!(!robots.contains("OAI-SearchBot") && !robots.contains("Claude-SearchBot"));
    assert!(
        !robots.contains("Sitemap:"),
        "no sitemap while indexing is off"
    );
    let (_, _, xml) = page(&f.router, "/sitemap.xml").await;
    assert!(xml.contains("<loc>https://example.test/de/gemeinden/261</loc>"));
    assert!(xml.contains("<loc>https://example.test/it/entscheide/dec-zh</loc>"));
    assert!(xml.contains("<loc>https://example.test/fr</loc>"));
    assert!(xml.contains("<loc>https://example.test/it/datenschutz</loc>"));
    let (status, headers, llms) = page(&f.router, "/llms.txt").await;
    assert_eq!(status, StatusCode::OK);
    assert!(
        headers[header::CONTENT_TYPE]
            .to_str()
            .unwrap()
            .starts_with("text/markdown")
    );
    assert!(llms.starts_with("# OpenCommune\n\n> Open archive"));
    assert!(llms.contains("[MCP server](https://example.test/mcp)"));

    let indexed = build(false, false, true).await;
    let (_, headers, _) = page(&indexed.router, "/de/gemeinden/261").await;
    assert!(headers.get("x-robots-tag").is_none());
    let (_, _, robots) = page(&indexed.router, "/robots.txt").await;
    assert!(robots.ends_with("Sitemap: https://example.test/sitemap.xml\n"));
}
