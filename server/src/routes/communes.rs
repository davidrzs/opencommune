//! `/api/communes`, `/api/register`.

use axum::Json;
use axum::extract::State;

use crate::AppState;
use crate::db::communes;
use crate::error::ApiResult;
use crate::models::{Commune, RegisterEntry};

pub async fn list(State(state): State<AppState>) -> ApiResult<Vec<Commune>> {
    Ok(Json(communes::list(&state.db).await?))
}

pub async fn register(State(state): State<AppState>) -> ApiResult<Vec<RegisterEntry>> {
    Ok(Json(communes::register(&state.db).await?))
}
