//! `/api/archive/*` for the front end and the `/original/{sha256}` redirect.

use axum::Json;
use axum::extract::State;
use axum::http::{HeaderValue, StatusCode, header};
use axum::response::{IntoResponse, Response};
use serde::Deserialize;

use crate::AppState;
use crate::db::{archive, communes};
use crate::error::{ApiError, ApiResult, Path, Query};
use crate::models::{ArchiveCommune, CataloguePage, SlimCommune};

pub async fn communes(State(state): State<AppState>) -> ApiResult<Vec<SlimCommune>> {
    Ok(Json(communes::slim(&state.db).await?))
}

pub async fn commune(
    State(state): State<AppState>,
    Path(bfs_id): Path<i64>,
) -> ApiResult<ArchiveCommune> {
    communes::detail(&state.db, bfs_id)
        .await?
        .map(Json)
        .ok_or_else(|| ApiError::not_found("commune not found"))
}

#[derive(Deserialize)]
pub struct DocumentParams {
    commune: Option<i64>,
    #[serde(default)]
    q: String,
    year: Option<i64>,
    offset: Option<i64>,
}

pub async fn documents(
    State(state): State<AppState>,
    Query(p): Query<DocumentParams>,
) -> ApiResult<CataloguePage> {
    if p.year.is_some_and(|y| !(1800..=2200).contains(&y)) {
        return Err(ApiError::invalid("year must be between 1800 and 2200"));
    }
    let offset = p.offset.unwrap_or(0);
    if offset < 0 {
        return Err(ApiError::invalid("offset must not be negative"));
    }
    Ok(Json(
        archive::documents(&state.db, p.commune, &p.q, p.year, offset).await?,
    ))
}

/// Redirect to a catalogued document on the commune's site.
pub async fn original(
    State(state): State<AppState>,
    Path(sha256): Path<String>,
) -> Result<Response, ApiError> {
    let url = archive::original(&state.db, &sha256)
        .await?
        .ok_or_else(|| ApiError::not_found("document not found"))?;
    let location = HeaderValue::from_str(&quote(&url))
        .map_err(|_| ApiError::not_found("document not found"))?;
    Ok((
        StatusCode::FOUND,
        [
            (header::LOCATION, location),
            (
                header::HeaderName::from_static("x-robots-tag"),
                HeaderValue::from_static("noindex, nofollow"),
            ),
        ],
    )
        .into_response())
}

/// Percent-encodes what a `Location` header cannot carry, keeping URL syntax characters
/// (`:/%#?=@[]!$&'()*+,;`) as they are.
fn quote(url: &str) -> String {
    const SAFE: &[u8] = b":/%#?=@[]!$&'()*+,;_.-~";
    let mut out = String::with_capacity(url.len());
    for &b in url.as_bytes() {
        if b.is_ascii_alphanumeric() || SAFE.contains(&b) {
            out.push(b as char);
        } else {
            out.push_str(&format!("%{b:02X}"));
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::quote;

    #[test]
    fn locations_are_percent_encoded() {
        assert_eq!(
            quote("https://a.ch/Gemeinderat Protokoll ä.pdf?x=1&y=2#p"),
            "https://a.ch/Gemeinderat%20Protokoll%20%C3%A4.pdf?x=1&y=2#p"
        );
    }
}
