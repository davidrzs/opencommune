//! Query functions, one per endpoint, grouped by area. Every query is read-only.

pub mod archive;
pub mod communes;
pub mod dataset;
pub mod decisions;

use std::path::Path;

use sqlx::sqlite::{SqliteConnectOptions, SqlitePool, SqlitePoolOptions};

/// A read-only pool on a database the Python pipeline builds.
pub async fn open_read_only(path: &Path) -> Result<SqlitePool, sqlx::Error> {
    let options = SqliteConnectOptions::new()
        .filename(path)
        .read_only(true)
        .create_if_missing(false);
    SqlitePoolOptions::new()
        .max_connections(8)
        .connect_with(options)
        .await
}

/// `lower(col) LIKE '%' || lower(?) || '%' ESCAPE '/'`: SQLAlchemy's `icontains(.., autoescape=True)`.
pub fn contains_pattern(text: &str) -> String {
    let mut out = String::with_capacity(text.len() + 2);
    out.push('%');
    for c in text.chars() {
        if matches!(c, '%' | '_' | '/') {
            out.push('/');
        }
        out.push(c);
    }
    out.push('%');
    out
}
