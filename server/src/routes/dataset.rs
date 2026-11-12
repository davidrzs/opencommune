//! `/api/dataset/*`: votes and finances from the dataset, when `DATASET_PATH` is set.

use axum::Json;
use axum::extract::State;
use serde_json::Value;
use sqlx::SqlitePool;

use crate::AppState;
use crate::db::dataset;
use crate::error::{ApiError, ApiResult, Path};

fn pool(state: &AppState) -> Result<&SqlitePool, ApiError> {
    state
        .dataset
        .as_ref()
        .ok_or_else(|| ApiError::not_found("dataset not configured"))
}

pub async fn commune(State(state): State<AppState>, Path(bfs_id): Path<i64>) -> ApiResult<Value> {
    Ok(Json(dataset::commune(pool(&state)?, bfs_id).await?))
}

pub async fn coverage(State(state): State<AppState>) -> ApiResult<Value> {
    Ok(Json(dataset::coverage(pool(&state)?).await?))
}

pub async fn findings(State(state): State<AppState>) -> ApiResult<Value> {
    Ok(Json(dataset::findings(pool(&state)?).await?))
}
