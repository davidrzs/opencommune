//! Query functions, one per endpoint, grouped by area. Every query is read-only.

pub mod communes;
pub mod documents;
pub mod pages;

use std::path::Path;

use sqlx::sqlite::{SqliteConnectOptions, SqlitePool, SqlitePoolOptions};

/// A read-only pool on the serving database the Python build writes.
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

/// Fails unless every table of `serving.sql` is there, so that a database of another build stops
/// the server at start instead of failing each request.
pub async fn check_tables(pool: &SqlitePool) -> Result<(), sqlx::Error> {
    sqlx::query(
        "SELECT 1 FROM communes, runs, documents, document_communes, sections, register, \
         register_publications, access_observations LIMIT 0",
    )
    .execute(pool)
    .await
    .map(drop)
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
