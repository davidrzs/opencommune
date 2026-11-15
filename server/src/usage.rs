//! In-house usage statistics in a separate SQLite file: daily aggregates per channel, route
//! template, bot flag and status, kept for good. No raw paths, query strings, search terms,
//! headers or IP addresses are stored. The daily visitor estimate keeps an HMAC of address and
//! browser under a key that is replaced every day; once the day is over its key and its HMACs are
//! deleted and only their number stays.

use std::net::SocketAddr;
use std::path::Path;
use std::time::{Duration, Instant};

use axum::extract::{ConnectInfo, MatchedPath, Request, State};
use axum::http::{HeaderMap, Method};
use axum::middleware::Next;
use axum::response::Response;
use hmac::{Hmac, KeyInit, Mac};
use sha2::Sha256;
use sqlx::SqlitePool;
use sqlx::sqlite::{SqliteConnectOptions, SqlitePoolOptions};

use crate::AppState;

const SCHEMA: &str = "
CREATE TABLE IF NOT EXISTS totals (
    day TEXT, channel TEXT, route TEXT, bot INTEGER, status INTEGER,
    requests INTEGER NOT NULL, searches INTEGER NOT NULL,
    empty_searches INTEGER NOT NULL, duration_ms REAL NOT NULL,
    PRIMARY KEY (day, channel, route, bot, status)
);
CREATE TABLE IF NOT EXISTS visitors (day TEXT, token TEXT, PRIMARY KEY (day, token));
CREATE TABLE IF NOT EXISTS daily_keys (day TEXT PRIMARY KEY, secret BLOB);
CREATE TABLE IF NOT EXISTS daily_visitors (day TEXT PRIMARY KEY, visitors INTEGER NOT NULL);
";

/// Set as a response extension by a handler that ran a search: the number of results.
#[derive(Clone, Copy)]
pub struct SearchTotal(pub i64);

/// One counted request.
pub struct Hit {
    pub channel: &'static str,
    pub route: String,
    pub bot: bool,
    pub status: u16,
    pub duration_ms: f64,
    pub search_total: Option<i64>,
    /// Client address and user agent; hashed, never stored.
    pub visitor: Option<(String, String)>,
}

#[derive(Clone)]
pub struct Usage {
    pool: SqlitePool,
    visitors: bool,
}

impl Usage {
    pub async fn open(path: &Path, visitors: bool) -> Result<Self, sqlx::Error> {
        if let Some(dir) = path.parent() {
            std::fs::create_dir_all(dir)?;
        }
        let options = SqliteConnectOptions::new()
            .filename(path)
            .create_if_missing(true)
            .busy_timeout(Duration::from_secs(1))
            .pragma("secure_delete", "ON");
        let pool = SqlitePoolOptions::new()
            .max_connections(1)
            .connect_with(options)
            .await?;
        sqlx::raw_sql(SCHEMA).execute(&pool).await?;
        Ok(Self { pool, visitors })
    }

    /// Store a hit in the background; a failure is logged and never reaches the request.
    pub fn record(&self, hit: Hit) {
        let pool = self.pool.clone();
        tokio::spawn(async move {
            if write(&pool, hit).await.is_err() {
                // no error details: they may contain environment details
                tracing::warn!("usage statistics could not be stored");
            }
        });
    }
}

async fn write(pool: &SqlitePool, hit: Hit) -> sqlx::Result<()> {
    let mut tx = pool.begin().await?;
    // the first statement writes, so the transaction holds the write lock from the start; a past
    // day's visitors become a number, and its HMACs and key go
    for statement in [
        "INSERT OR IGNORE INTO daily_visitors \
         SELECT day, count(*) FROM visitors WHERE day < date('now') GROUP BY day",
        "DELETE FROM visitors WHERE day < date('now')",
        "DELETE FROM daily_keys WHERE day != date('now')",
    ] {
        sqlx::query(statement).execute(&mut *tx).await?;
    }
    sqlx::query(
        "INSERT INTO totals VALUES (date('now'), ?, ?, ?, ?, 1, ?, ?, ?) \
         ON CONFLICT (day, channel, route, bot, status) DO UPDATE SET \
         requests = requests + 1, searches = searches + excluded.searches, \
         empty_searches = empty_searches + excluded.empty_searches, \
         duration_ms = duration_ms + excluded.duration_ms",
    )
    .bind(hit.channel)
    .bind(&hit.route)
    .bind(hit.bot)
    .bind(i64::from(hit.status))
    .bind(hit.search_total.is_some())
    .bind(hit.search_total == Some(0))
    .bind(hit.duration_ms)
    .execute(&mut *tx)
    .await?;
    if let Some(visitor) = &hit.visitor
        && hit.channel == "web"
        && !hit.bot
        && (200..300).contains(&hit.status)
    {
        sqlx::query("INSERT OR IGNORE INTO daily_keys VALUES (date('now'), randomblob(32))")
            .execute(&mut *tx)
            .await?;
        let key: Vec<u8> =
            sqlx::query_scalar("SELECT secret FROM daily_keys WHERE day = date('now')")
                .fetch_one(&mut *tx)
                .await?;
        sqlx::query("INSERT OR IGNORE INTO visitors VALUES (date('now'), ?)")
            .bind(token(&key, visitor))
            .execute(&mut *tx)
            .await?;
    }
    tx.commit().await
}

fn token(key: &[u8], visitor: &(String, String)) -> String {
    let mut mac = <Hmac<Sha256> as KeyInit>::new_from_slice(key).expect("HMAC takes any key");
    mac.update(
        serde_json::to_string(visitor)
            .unwrap_or_default()
            .as_bytes(),
    );
    mac.finalize()
        .into_bytes()
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}

/// Recognisable automated clients; a heuristic.
pub fn is_bot(user_agent: &str) -> bool {
    const MARKERS: [&str; 9] = [
        "bot", "crawler", "spider", "slurp", "headless", "curl", "wget", "python", "httpx",
    ];
    let ua = user_agent.to_ascii_lowercase();
    ua.is_empty() || MARKERS.iter().any(|m| ua.contains(m))
}

/// The route template of a page, without the language prefix; None for anything else (assets,
/// unknown paths).
pub fn page_template(path: &str) -> Option<&'static str> {
    match path {
        "/robots.txt" => return Some("/robots.txt"),
        "/sitemap.xml" => return Some("/sitemap.xml"),
        "/llms.txt" => return Some("/llms.txt"),
        _ => {}
    }
    let rest = ["/de", "/fr", "/it"]
        .iter()
        .find_map(|l| {
            path.strip_prefix(l)
                .filter(|r| r.is_empty() || r.starts_with('/'))
        })
        .unwrap_or(path);
    match rest {
        "" | "/" => Some("/"),
        "/suche" => Some("/suche"),
        "/ueber-uns" => Some("/ueber-uns"),
        "/datenschutz" => Some("/datenschutz"),
        _ => rest
            .strip_prefix("/gemeinden/")
            .filter(|id| !id.is_empty() && id.bytes().all(|b| b.is_ascii_digit()))
            .map(|_| "/gemeinden/{id}"),
    }
}

/// The channel and route a request is counted under, or None when it is not counted.
fn classify(matched: Option<&str>, path: &str) -> Option<(&'static str, String)> {
    match matched {
        // MCP tools are counted one by one by the MCP handler
        Some("/mcp") | Some("/api/{*rest}") => None,
        Some(route) if route.starts_with("/api/") => Some(("api", route.to_string())),
        Some(route @ "/original/{sha256}") => Some(("original", route.to_string())),
        // pages, whether the server renders their facts or only serves the front end
        _ => page_template(path).map(|r| ("web", r.to_string())),
    }
}

/// The client's address: the peer, or behind a reverse proxy on this machine the address it
/// forwards. Forwarded headers from anyone else are ignored.
fn client_address(peer: Option<SocketAddr>, headers: &HeaderMap) -> Option<String> {
    let peer = peer?;
    if peer.ip().is_loopback()
        && let Some(forwarded) = headers
            .get("x-forwarded-for")
            .and_then(|v| v.to_str().ok())
            .and_then(|v| v.rsplit(',').next())
            .map(str::trim)
            .filter(|v| !v.is_empty())
    {
        return Some(forwarded.to_string());
    }
    Some(peer.ip().to_string())
}

/// Middleware: count GET requests to API routes, the document redirect and front-end pages.
pub async fn count(State(state): State<AppState>, request: Request, next: Next) -> Response {
    let Some(usage) = state.usage.clone() else {
        return next.run(request).await;
    };
    let matched = request
        .extensions()
        .get::<MatchedPath>()
        .map(|m| m.as_str());
    let counted = if request.method() == Method::GET {
        classify(matched, request.uri().path())
    } else {
        None
    };
    let Some((channel, route)) = counted else {
        return next.run(request).await;
    };
    let headers = request.headers();
    let header = |name: &str| {
        headers
            .get(name)
            .and_then(|v| v.to_str().ok())
            .unwrap_or("")
    };
    let user_agent = header("user-agent").to_string();
    let bot = is_bot(&user_agent);
    let opted_out = header("dnt") == "1" || header("sec-gpc") == "1";
    let visitor = if usage.visitors && channel == "web" && !bot && !opted_out {
        let peer = request
            .extensions()
            .get::<ConnectInfo<SocketAddr>>()
            .map(|c| c.0);
        client_address(peer, headers).map(|address| (address, user_agent))
    } else {
        None
    };
    let started = Instant::now();
    let response = next.run(request).await;
    usage.record(Hit {
        channel,
        route,
        bot,
        status: response.status().as_u16(),
        duration_ms: started.elapsed().as_secs_f64() * 1000.0,
        search_total: response.extensions().get::<SearchTotal>().map(|s| s.0),
        visitor,
    });
    response
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pages_are_counted_by_template() {
        assert_eq!(page_template("/"), Some("/"));
        assert_eq!(page_template("/fr"), Some("/"));
        assert_eq!(page_template("/de/gemeinden/261"), Some("/gemeinden/{id}"));
        assert_eq!(page_template("/gemeinden/261"), Some("/gemeinden/{id}"));
        assert_eq!(page_template("/it/suche"), Some("/suche"));
        assert_eq!(page_template("/_app/immutable/x.js"), None);
        assert_eq!(page_template("/dex"), None);
        assert_eq!(page_template("/de/gemeinden/x"), None);
        assert_eq!(page_template("/fr/entscheide/dec-1a"), None);
        assert_eq!(page_template("/llms.txt"), Some("/llms.txt"));
    }

    #[test]
    fn forwarded_addresses_are_trusted_from_loopback_only() {
        let mut headers = HeaderMap::new();
        headers.insert(
            "x-forwarded-for",
            "203.0.113.9, 198.51.100.7".parse().unwrap(),
        );
        let local = Some("127.0.0.1:5000".parse().unwrap());
        let remote = Some("192.0.2.1:5000".parse().unwrap());
        assert_eq!(
            client_address(local, &headers).as_deref(),
            Some("198.51.100.7")
        );
        assert_eq!(
            client_address(remote, &headers).as_deref(),
            Some("192.0.2.1")
        );
    }

    #[test]
    fn bots_are_recognised() {
        assert!(is_bot(""));
        assert!(is_bot("curl/8.0"));
        assert!(is_bot("Googlebot/2.1"));
        assert!(!is_bot("Mozilla/5.0 (X11; Linux x86_64) Firefox/140.0"));
    }
}
