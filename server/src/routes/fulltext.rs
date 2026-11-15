//! `/api/pages` (full-text search) and `/api/documents/{sha256}/pages` (the text of pages). Both
//! answer 503 when the server has no full-text index.

use axum::Json;
use axum::extract::State;
use axum::response::{IntoResponse, Response};

use crate::AppState;
use crate::db::fulltext::{self, PageRange, TextSearch, UNAVAILABLE};
use crate::error::{ApiError, ApiResult, Path, Query};
use crate::models::DocumentPages;
use crate::usage::SearchTotal;

pub async fn search(
    State(state): State<AppState>,
    Query(search): Query<TextSearch>,
) -> Result<Response, ApiError> {
    if !state.fulltext {
        return Err(ApiError::unavailable(UNAVAILABLE));
    }
    let query = search.check().map_err(ApiError::invalid)?;
    let page = fulltext::search(&state.db, &search, &query).await?;
    let total = page.total;
    let mut response = Json(page).into_response();
    // a first page is a search in the usage statistics; further pages are not
    if search.offset == 0 {
        response.extensions_mut().insert(SearchTotal(total));
    }
    Ok(response)
}

pub async fn pages(
    State(state): State<AppState>,
    Path(sha256): Path<String>,
    Query(range): Query<PageRange>,
) -> ApiResult<DocumentPages> {
    if !state.fulltext {
        return Err(ApiError::unavailable(UNAVAILABLE));
    }
    let (from, to) = range.check().map_err(ApiError::invalid)?;
    fulltext::read(&state.db, &sha256, from, to)
        .await?
        .map(Json)
        .ok_or_else(|| ApiError::not_found("document not found"))
}
