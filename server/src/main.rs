use std::io::IsTerminal;
use std::net::SocketAddr;
use std::process::ExitCode;

use opencommune_server::config::Config;
use opencommune_server::site::Site;
use opencommune_server::usage::Usage;
use opencommune_server::{AppState, app, db};
use tokio::net::TcpListener;
use tracing_subscriber::EnvFilter;

#[tokio::main]
async fn main() -> ExitCode {
    tracing_subscriber::fmt()
        .with_ansi(std::io::stdout().is_terminal())
        .with_env_filter(
            EnvFilter::try_from_default_env().unwrap_or_else(|_| "info,rmcp=warn".into()),
        )
        .init();
    match run().await {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            tracing::error!(%error, "server stopped");
            ExitCode::FAILURE
        }
    }
}

async fn run() -> Result<(), Box<dyn std::error::Error>> {
    let config = Config::from_env()?;
    let db = db::open_read_only(&config.database_path)
        .await
        .map_err(|e| format!("{}: {e}", config.database_path.display()))?;
    db::check_tables(&db).await.map_err(|e| {
        format!(
            "{}: not a serving database: {e}",
            config.database_path.display()
        )
    })?;
    let usage = match &config.usage_path {
        Some(path) => match Usage::open(path, config.usage_visitors).await {
            Ok(usage) => Some(usage),
            Err(error) => {
                tracing::warn!(%error, path = %path.display(), "usage statistics disabled");
                None
            }
        },
        None => None,
    };
    if !config.static_dir.join("index.html").is_file() {
        tracing::warn!(path = %config.static_dir.display(), "no index.html: the front end is not built");
    }
    let site = Site::new(
        &config.public_url,
        config.search_indexing,
        &config.static_dir,
    );
    let state = AppState { db, usage, site };
    let router = app(state, &config.static_dir, &config.mcp_allowed_hosts);
    let listener = TcpListener::bind(config.bind).await?;
    tracing::info!(
        bind = %config.bind,
        database = %config.database_path.display(),
        "listening"
    );
    axum::serve(
        listener,
        router.into_make_service_with_connect_info::<SocketAddr>(),
    )
    .with_graceful_shutdown(shutdown())
    .await?;
    Ok(())
}

async fn shutdown() {
    let terminate = async {
        match tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate()) {
            Ok(mut signal) => {
                signal.recv().await;
            }
            Err(_) => std::future::pending().await,
        }
    };
    tokio::select! {
        _ = tokio::signal::ctrl_c() => {},
        () = terminate => {},
    }
    tracing::info!("shutting down");
}
