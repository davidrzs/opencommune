//! `/api/communes`, `/api/communes/{bfs_id}`, `/api/register`.

use axum::Json;
use axum::extract::State;

use crate::AppState;
use crate::db::communes;
use crate::error::{ApiError, ApiResult, Path};
use crate::models::{Commune, CommuneDetail, RegisterEntry};

pub async fn list(State(state): State<AppState>) -> ApiResult<Vec<Commune>> {
    Ok(Json(communes::list(&state.db).await?))
}

pub async fn detail(
    State(state): State<AppState>,
    Path(bfs_id): Path<i64>,
) -> ApiResult<CommuneDetail> {
    communes::detail(&state.db, bfs_id)
        .await?
        .map(Json)
        .ok_or_else(|| ApiError::not_found("commune not found"))
}

pub async fn register(State(state): State<AppState>) -> ApiResult<Vec<RegisterEntry>> {
    Ok(Json(communes::register(&state.db).await?))
}
