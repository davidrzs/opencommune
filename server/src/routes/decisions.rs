//! `/api/decisions`, `/api/documents`, `/api/stats`.

use axum::Json;
use axum::extract::State;
use axum::response::{IntoResponse, Response};
use serde::Deserialize;

use super::valid_date;
use crate::AppState;
use crate::db::decisions::{self, SearchFilters};
use crate::error::{ApiError, ApiResult, Path, Query};
use crate::models::{Decision, DocumentItem, SearchPage};
use crate::usage::SearchTotal;

#[derive(Deserialize)]
pub struct SearchParams {
    q: Option<String>,
    commune: Option<i64>,
    canton: Option<String>,
    category: Option<String>,
    outcome: Option<String>,
    lang: Option<String>,
    body: Option<String>,
    #[serde(rename = "from")]
    date_from: Option<String>,
    #[serde(rename = "to")]
    date_to: Option<String>,
    min_amount: Option<f64>,
    limit: Option<i64>,
    offset: Option<i64>,
}

pub async fn search(
    State(state): State<AppState>,
    Query(p): Query<SearchParams>,
) -> Result<Response, ApiError> {
    let limit = p.limit.unwrap_or(20);
    let offset = p.offset.unwrap_or(0);
    if !(1..=200).contains(&limit) {
        return Err(ApiError::invalid("limit must be between 1 and 200"));
    }
    if offset < 0 {
        return Err(ApiError::invalid("offset must not be negative"));
    }
    for date in [&p.date_from, &p.date_to].into_iter().flatten() {
        if !valid_date(date) {
            return Err(ApiError::invalid(format!(
                "{date:?} is not a date (YYYY-MM-DD)"
            )));
        }
    }
    let filters = SearchFilters {
        q: p.q,
        commune: p.commune,
        canton: p.canton,
        category: p.category,
        outcome: p.outcome,
        lang: p.lang,
        body: p.body,
        date_from: p.date_from,
        date_to: p.date_to,
        min_amount: p.min_amount,
        limit,
        offset,
    };
    let res = decisions::search(&state.db, &filters).await?;
    // a search is a first page with a query or a filter
    let filtered = [
        &filters.q,
        &filters.canton,
        &filters.category,
        &filters.outcome,
        &filters.lang,
        &filters.body,
        &filters.date_from,
        &filters.date_to,
    ]
    .iter()
    .any(|v| v.as_deref().is_some_and(|s| !s.is_empty()))
        || filters.commune.is_some_and(|c| c != 0)
        || filters.min_amount.is_some_and(|a| a != 0.0);
    let total = res.total;
    let mut response = Json(SearchPage {
        total: res.total,
        mode: res.mode,
        limit,
        offset,
        items: res.items,
    })
    .into_response();
    if offset == 0 && filtered {
        response.extensions_mut().insert(SearchTotal(total));
    }
    Ok(response)
}

pub async fn get(
    State(state): State<AppState>,
    Path(decision_id): Path<String>,
) -> ApiResult<Decision> {
    decisions::get(&state.db, &decision_id)
        .await?
        .map(Json)
        .ok_or_else(|| ApiError::not_found("decision not found"))
}

#[derive(Deserialize)]
pub struct DocumentParams {
    commune: Option<i64>,
    body: Option<String>,
}

pub async fn documents(
    State(state): State<AppState>,
    Query(p): Query<DocumentParams>,
) -> ApiResult<Vec<DocumentItem>> {
    Ok(Json(
        decisions::documents(&state.db, p.commune, p.body.as_deref()).await?,
    ))
}

pub async fn stats(State(state): State<AppState>) -> ApiResult<decisions::Stats> {
    Ok(Json(decisions::stats(&state.db).await?))
}
