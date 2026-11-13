//! HTTP routes, one handler per endpoint, grouped by area. Handlers parse and validate
//! parameters, call one query function in `db` and return JSON.

mod archive;
mod communes;
mod dataset;
mod decisions;
mod pages;

use axum::Router;
use axum::extract::{Path, State};
use axum::routing::get;

use crate::AppState;
use crate::error::ApiError;
use crate::site::Lang;

pub fn router() -> Router<AppState> {
    let mut router = Router::new()
        .route("/api/communes", get(communes::list))
        .route("/api/register", get(communes::register))
        .route("/api/documents", get(decisions::documents))
        .route("/api/decisions", get(decisions::search))
        .route("/api/decisions/{decision_id}", get(decisions::get))
        .route("/api/stats", get(decisions::stats))
        .route("/api/archive/communes", get(archive::communes))
        .route("/api/archive/communes/{bfs_id}", get(archive::commune))
        .route("/api/archive/documents", get(archive::documents))
        .route("/api/dataset/communes/{bfs_id}", get(dataset::commune))
        .route("/api/dataset/coverage", get(dataset::coverage))
        .route("/api/dataset/findings", get(dataset::findings))
        .route("/api/{*rest}", get(not_found))
        .route("/original/{sha256}", get(archive::original))
        .route("/robots.txt", get(pages::robots))
        .route("/sitemap.xml", get(pages::sitemap))
        .route("/llms.txt", get(pages::llms))
        .route("/", get(pages::root));
    // the pages crawlers read, in each language; the front end serves every other path
    for lang in Lang::ALL {
        let base = format!("/{}", lang.code());
        router = router
            .route(
                &base,
                get(move |State(s): State<AppState>| pages::home(s, lang)),
            )
            .route(
                &format!("{base}/gemeinden/{{id}}"),
                get(move |State(s): State<AppState>, Path(id): Path<String>| {
                    pages::commune(s, lang, id)
                }),
            )
            .route(
                &format!("{base}/entscheide/{{id}}"),
                get(move |State(s): State<AppState>, Path(id): Path<String>| {
                    pages::decision(s, lang, id)
                }),
            )
            .route(
                &format!("{base}/ueber-uns"),
                get(move |State(s): State<AppState>| pages::about(s, lang)),
            )
            .route(
                &format!("{base}/datenschutz"),
                get(move |State(s): State<AppState>| pages::privacy(s, lang)),
            )
            .route(
                &format!("{base}/suche"),
                get(move |State(s): State<AppState>| pages::search(s, lang)),
            );
    }
    router
}

async fn not_found() -> ApiError {
    ApiError::not_found("Not Found")
}

/// An ISO date `YYYY-MM-DD` that exists.
pub fn valid_date(s: &str) -> bool {
    let b = s.as_bytes();
    if b.len() != 10 || b[4] != b'-' || b[7] != b'-' {
        return false;
    }
    let num = |r: std::ops::Range<usize>| {
        s.get(r)
            .filter(|p| p.bytes().all(|c| c.is_ascii_digit()))?
            .parse::<u32>()
            .ok()
    };
    let (Some(y), Some(m), Some(d)) = (num(0..4), num(5..7), num(8..10)) else {
        return false;
    };
    let leap = (y % 4 == 0 && y % 100 != 0) || y % 400 == 0;
    let days = match m {
        1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
        4 | 6 | 9 | 11 => 30,
        2 if leap => 29,
        2 => 28,
        _ => return false,
    };
    y >= 1 && (1..=days).contains(&d)
}

#[cfg(test)]
mod tests {
    use super::valid_date;

    #[test]
    fn dates_are_checked() {
        assert!(valid_date("2024-02-29"));
        assert!(!valid_date("2023-02-29"));
        assert!(!valid_date("2024-13-01"));
        assert!(!valid_date("2024-1-01"));
        assert!(!valid_date("yesterday"));
    }
}
