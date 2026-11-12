//! Configuration from the environment, with defaults for a checkout of the repository.

use std::env;
use std::net::SocketAddr;
use std::path::PathBuf;

#[derive(Clone, Debug)]
pub struct Config {
    /// `DATABASE_PATH`: the archive database the Python build writes; opened read-only.
    pub database_path: PathBuf,
    /// `DATASET_PATH`: the dataset SQLite; unset, `/api/dataset/*` answers 404.
    pub dataset_path: Option<PathBuf>,
    /// `STATIC_DIR`: the built front end (`frontend/build`).
    pub static_dir: PathBuf,
    /// `BIND`: the address to listen on.
    pub bind: SocketAddr,
    /// `USAGE_PATH`: the usage statistics SQLite; `None` when `USAGE_ENABLED=false`.
    pub usage_path: Option<PathBuf>,
    /// `USAGE_VISITORS`: estimate daily visitors.
    pub usage_visitors: bool,
    /// `MCP_ALLOWED_HOSTS`: comma-separated `Host` values `/mcp` accepts (DNS rebinding guard).
    pub mcp_allowed_hosts: Vec<String>,
}

impl Config {
    pub fn from_env() -> Result<Self, String> {
        let bind = var("BIND")
            .unwrap_or_else(|| "127.0.0.1:8000".into())
            .parse()
            .map_err(|e| format!("BIND: {e}"))?;
        let usage_enabled = flag("USAGE_ENABLED", true)?;
        Ok(Self {
            database_path: var("DATABASE_PATH")
                .unwrap_or_else(|| "data/opencommune.db".into())
                .into(),
            dataset_path: var("DATASET_PATH").map(PathBuf::from),
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
            mcp_allowed_hosts: var("MCP_ALLOWED_HOSTS")
                .unwrap_or_else(|| "localhost,127.0.0.1,::1".into())
                .split(',')
                .map(|h| h.trim().to_string())
                .filter(|h| !h.is_empty())
                .collect(),
        })
    }
}

fn var(name: &str) -> Option<String> {
    env::var(name).ok().filter(|v| !v.trim().is_empty())
}

fn flag(name: &str, default: bool) -> Result<bool, String> {
    match var(name).map(|v| v.trim().to_ascii_lowercase()).as_deref() {
        None => Ok(default),
        Some("1" | "true" | "yes" | "on") => Ok(true),
        Some("0" | "false" | "no" | "off") => Ok(false),
        Some(other) => Err(format!("{name}: {other:?} is not a boolean")),
    }
}
