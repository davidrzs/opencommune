//! Configuration from the environment, with defaults for a checkout of the repository.

use std::env;
use std::net::SocketAddr;
use std::path::PathBuf;

#[derive(Clone, Debug)]
pub struct Config {
    /// `DATABASE_PATH`: the serving database the Python build writes; opened read-only.
    pub database_path: PathBuf,
    /// `FULLTEXT_PATH`: the full-text index of page text the Python build writes; attached
    /// read-only when the file exists. Defaults to `fulltext.db` next to the serving database.
    pub fulltext_path: PathBuf,
    /// `STATIC_DIR`: the built front end (`frontend/build`).
    pub static_dir: PathBuf,
    /// `BIND`: the address to listen on.
    pub bind: SocketAddr,
    /// `USAGE_PATH`: the usage statistics SQLite; `None` when `USAGE_ENABLED=false`.
    pub usage_path: Option<PathBuf>,
    /// `USAGE_VISITORS`: estimate daily visitors.
    pub usage_visitors: bool,
    /// `USAGE_TOKEN`: the token `GET /api/usage` asks for (at least 32 characters); without one
    /// the report is off.
    pub usage_token: Option<String>,
    /// `MCP_ALLOWED_HOSTS`: comma-separated `Host` values `/mcp` accepts (DNS rebinding guard).
    pub mcp_allowed_hosts: Vec<String>,
    /// `PUBLIC_URL`: the site's address in canonical links, the sitemap and `llms.txt`.
    pub public_url: String,
    /// `FORMER_HOSTS`: comma-separated former names of the site; their requests are sent on to
    /// `PUBLIC_URL`.
    pub former_hosts: Vec<String>,
    /// `SEARCH_INDEXING`: let search engines index the pages; off, every response says `noindex`.
    pub search_indexing: bool,
    /// `SEARCH_INDEX_COMMUNES`: let them index the commune pages too; off, those pages say
    /// `noindex` and stay out of the sitemap.
    pub search_index_communes: bool,
}

impl Config {
    pub fn from_env() -> Result<Self, String> {
        let bind = var("BIND")
            .unwrap_or_else(|| "127.0.0.1:8000".into())
            .parse()
            .map_err(|e| format!("BIND: {e}"))?;
        let usage_enabled = flag("USAGE_ENABLED", true)?;
        let usage_token = var("USAGE_TOKEN").map(|t| t.trim().to_string());
        if usage_token.as_ref().is_some_and(|t| t.len() < 32) {
            return Err("USAGE_TOKEN: shorter than 32 characters".into());
        }
        let database_path: PathBuf = var("DATABASE_PATH")
            .unwrap_or_else(|| "data/opencommune.db".into())
            .into();
        Ok(Self {
            fulltext_path: var("FULLTEXT_PATH").map_or_else(
                || database_path.with_file_name("fulltext.db"),
                PathBuf::from,
            ),
            database_path,
            static_dir: var("STATIC_DIR")
                .unwrap_or_else(|| "frontend/build".into())
                .into(),
            bind,
            usage_path: usage_enabled.then(|| {
                var("USAGE_PATH")
                    .unwrap_or_else(|| "data/logs/usage.sqlite3".into())
                    .into()
            }),
            usage_visitors: flag("USAGE_VISITORS", true)?,
            usage_token,
            mcp_allowed_hosts: list("MCP_ALLOWED_HOSTS", "localhost,127.0.0.1,::1"),
            public_url: var("PUBLIC_URL").unwrap_or_else(|| format!("http://{bind}")),
            former_hosts: list("FORMER_HOSTS", ""),
            search_indexing: flag("SEARCH_INDEXING", false)?,
            search_index_communes: flag("SEARCH_INDEX_COMMUNES", false)?,
        })
    }
}

fn var(name: &str) -> Option<String> {
    env::var(name).ok().filter(|v| !v.trim().is_empty())
}

/// A comma-separated list.
fn list(name: &str, default: &str) -> Vec<String> {
    var(name)
        .unwrap_or_else(|| default.into())
        .split(',')
        .map(|h| h.trim().to_string())
        .filter(|h| !h.is_empty())
        .collect()
}

fn flag(name: &str, default: bool) -> Result<bool, String> {
    match var(name).map(|v| v.trim().to_ascii_lowercase()).as_deref() {
        None => Ok(default),
        Some("1" | "true" | "yes" | "on") => Ok(true),
        Some("0" | "false" | "no" | "off") => Ok(false),
        Some(other) => Err(format!("{name}: {other:?} is not a boolean")),
    }
}
