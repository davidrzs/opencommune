//! MCP server over streamable HTTP at `/mcp`: search, one decision and the commune list, on the
//! same queries as the REST API. Stateless: every request is answered on its own, no session is kept.

use std::sync::Arc;
use std::time::Instant;

use rmcp::handler::server::wrapper::Parameters;
use rmcp::model::{CallToolResult, ContentBlock};
use rmcp::schemars::JsonSchema;
use rmcp::transport::streamable_http_server::session::local::LocalSessionManager;
use rmcp::transport::{StreamableHttpServerConfig, StreamableHttpService};
use rmcp::{ErrorData, ServerHandler, tool, tool_handler, tool_router};
use serde::Deserialize;
use serde_json::{Value, json};

use crate::AppState;
use crate::db::{communes, decisions};
use crate::routes::valid_date;
use crate::usage::Hit;

const SEARCH_DESCRIPTION: &str = "Search council decisions. `query` is free text over title and \
summary (diacritics-insensitive). Filters: `canton` two-letter code, `category` one of zoning, \
building_permit, finance_budget, finance_credit, personnel, infrastructure, school, social, \
naturalization, election, bylaw, procurement, other, `outcome` one of approved, rejected, \
postponed, noted, `language` de/fr/it, ISO dates, `min_amount_chf`. Returns total count and items \
with summary, amount, votes, commune, meeting date and a link to the source PDF page.";

#[derive(Deserialize, JsonSchema)]
#[schemars(crate = "rmcp::schemars")]
pub struct SearchArgs {
    #[serde(default)]
    query: Option<String>,
    #[serde(default)]
    commune_bfs_id: Option<i64>,
    #[serde(default)]
    canton: Option<String>,
    #[serde(default)]
    category: Option<String>,
    #[serde(default)]
    outcome: Option<String>,
    #[serde(default)]
    language: Option<String>,
    #[serde(default)]
    date_from: Option<String>,
    #[serde(default)]
    date_to: Option<String>,
    #[serde(default)]
    min_amount_chf: Option<f64>,
    #[serde(default = "default_limit")]
    limit: i64,
}

fn default_limit() -> i64 {
    20
}

#[derive(Deserialize, JsonSchema)]
#[schemars(crate = "rmcp::schemars")]
pub struct DecisionArgs {
    decision_id: String,
}

#[derive(Clone)]
pub struct Archive {
    state: AppState,
}

impl Archive {
    fn count(&self, tool: &str, started: Instant, status: u16, search_total: Option<i64>) {
        if let Some(usage) = &self.state.usage {
            usage.record(Hit {
                channel: "mcp",
                route: tool.to_string(),
                bot: false,
                status,
                duration_ms: started.elapsed().as_secs_f64() * 1000.0,
                search_total,
                visitor: None,
            });
        }
    }
}

fn internal(error: sqlx::Error) -> ErrorData {
    tracing::error!(%error, "database query failed");
    ErrorData::internal_error("database query failed", None)
}

#[tool_router]
impl Archive {
    #[tool(description = SEARCH_DESCRIPTION)]
    async fn search_decisions(
        &self,
        Parameters(args): Parameters<SearchArgs>,
    ) -> Result<CallToolResult, ErrorData> {
        let started = Instant::now();
        for date in [&args.date_from, &args.date_to].into_iter().flatten() {
            if !valid_date(date) {
                self.count("search_decisions", started, 422, None);
                return Ok(CallToolResult::error(vec![ContentBlock::text(format!(
                    "Error executing tool search_decisions: {date:?} is not an ISO date (YYYY-MM-DD)"
                ))]));
            }
        }
        let filters = decisions::SearchFilters {
            q: args.query,
            commune: args.commune_bfs_id,
            canton: args.canton,
            category: args.category,
            outcome: args.outcome,
            lang: args.language,
            body: None,
            date_from: args.date_from,
            date_to: args.date_to,
            min_amount: args.min_amount_chf,
            limit: args.limit.clamp(1, 100),
            offset: 0,
        };
        let res = decisions::search(&self.state.db, &filters)
            .await
            .map_err(internal)?;
        self.count("search_decisions", started, 200, Some(res.total));
        Ok(CallToolResult::structured(json!({
            "total": res.total,
            "mode": res.mode,
            "items": res.items,
        })))
    }

    /// Fetch one decision by id with all fields and provenance (source PDF, page span, model).
    #[tool]
    async fn get_decision(
        &self,
        Parameters(args): Parameters<DecisionArgs>,
    ) -> Result<CallToolResult, ErrorData> {
        let started = Instant::now();
        let decision = decisions::get(&self.state.db, &args.decision_id)
            .await
            .map_err(internal)?;
        self.count(
            "get_decision",
            started,
            if decision.is_some() { 200 } else { 404 },
            None,
        );
        Ok(CallToolResult::structured(match decision {
            Some(d) => serde_json::to_value(d).unwrap_or(Value::Null),
            None => json!({"error": "not found"}),
        }))
    }

    /// List covered communes with canton, language, website, and document and decision counts.
    #[tool]
    async fn list_communes(&self) -> Result<CallToolResult, ErrorData> {
        let started = Instant::now();
        let list = communes::list(&self.state.db).await.map_err(internal)?;
        self.count("list_communes", started, 200, None);
        Ok(CallToolResult::structured(json!({ "result": list })))
    }
}

#[tool_handler(
    name = "opencommune",
    instructions = "OpenCommune is an open archive of decisions taken by Swiss municipal councils and assemblies, extracted from published minutes in German, French and Italian and anonymised. Use search_decisions for keyword and filtered search, get_decision for full details, and list_communes to see coverage. Every decision links to the source PDF and page."
)]
impl ServerHandler for Archive {}

/// The `/mcp` endpoint.
pub fn service(
    state: AppState,
    allowed_hosts: &[String],
) -> StreamableHttpService<Archive, LocalSessionManager> {
    let config = StreamableHttpServerConfig::default()
        .with_legacy_session_mode(false)
        .with_json_response(true)
        .with_allowed_hosts(allowed_hosts.to_vec());
    StreamableHttpService::new(
        move || Ok(Archive::new(state.clone())),
        Arc::new(LocalSessionManager::default()),
        config,
    )
}

impl Archive {
    fn new(state: AppState) -> Self {
        Archive { state }
    }
}
