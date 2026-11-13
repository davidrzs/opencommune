//! MCP server over streamable HTTP at `/mcp`: the commune list, the document search and one
//! document, on the same queries as the REST API. Stateless: every request is answered on its own,
//! no session is kept.

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
use crate::db::communes;
use crate::db::documents::{self, Search};
use crate::usage::Hit;

const SEARCH_DESCRIPTION: &str = "Search the archive's documents, newest first. Every filter is \
optional; filters combine with AND. `commune`: a BFS number from list_communes. `section`: \
documents with at least one section of this type (minutes, decisions, vote_result, budget, \
accounts, invitation_agenda, proposal, member_request, regulation, report, notice, plan_or_map, \
news, other, unclear). `family`: documents with at least one section of this family \
(deliberation, money, proposals, rules, information, other). `body`: parliament, \
citizens_assembly, executive, commission, commune, other_public_body, private or unknown. `year`: \
the year of the document's date, else the one year the classifier read, else the year of the \
commune's listing date. `q`: text the document's title contains, case-insensitive. `limit` 0 to \
100 (default 20) and `offset` page through the results. Returns `total`, `facets` (documents per \
year, section type and body, each counted with every filter except its own) and `items`: title \
and body as printed (private names appear as [name]), dates, pages, sections with their family \
and pages, the communes that link the document, and `original_url`, a path on this site that \
redirects to the file on the commune's website (add `?page=N` to open it at a page). Titles, \
bodies, dates and sections come from an automatic classification by a language model that no \
person has checked yet.";

const GET_DESCRIPTION: &str = "Fetch one document by its sha256 (from search_documents) with \
every field and `run`: the classification run that gave its title, body, dates and sections, with \
the model and a note on what the run's settings do to the data. Titles, bodies, dates and \
sections come from an automatic classification by a language model that no person has checked \
yet.";

#[derive(Deserialize, JsonSchema)]
#[schemars(crate = "rmcp::schemars")]
pub struct DocumentArgs {
    /// The document's sha256, from search_documents.
    sha256: String,
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
    #[tool(
        title = "Search documents",
        description = SEARCH_DESCRIPTION,
        annotations(
            title = "Search documents",
            read_only_hint = true,
            destructive_hint = false,
            idempotent_hint = true,
            open_world_hint = false
        )
    )]
    async fn search_documents(
        &self,
        Parameters(search): Parameters<Search>,
    ) -> Result<CallToolResult, ErrorData> {
        let started = Instant::now();
        if let Err(reason) = search.check() {
            self.count("search_documents", started, 400, None);
            return Ok(CallToolResult::error(vec![ContentBlock::text(format!(
                "Error executing tool search_documents: {reason}"
            ))]));
        }
        let page = documents::search(&self.state.db, &search)
            .await
            .map_err(internal)?;
        let total = search.is_search().then_some(page.total);
        self.count("search_documents", started, 200, total);
        Ok(CallToolResult::structured(
            serde_json::to_value(page).unwrap_or(Value::Null),
        ))
    }

    #[tool(
        title = "Get a document",
        description = GET_DESCRIPTION,
        annotations(
            title = "Get a document",
            read_only_hint = true,
            destructive_hint = false,
            idempotent_hint = true,
            open_world_hint = false
        )
    )]
    async fn get_document(
        &self,
        Parameters(args): Parameters<DocumentArgs>,
    ) -> Result<CallToolResult, ErrorData> {
        let started = Instant::now();
        let document = documents::get(&self.state.db, &args.sha256)
            .await
            .map_err(internal)?;
        self.count(
            "get_document",
            started,
            if document.is_some() { 200 } else { 404 },
            None,
        );
        Ok(CallToolResult::structured(match document {
            Some(d) => serde_json::to_value(d).unwrap_or(Value::Null),
            None => json!({"error": "not found"}),
        }))
    }

    /// List the communes in the archive with canton, language, website, coordinates, number of
    /// documents and the coverage register's status and note. Use it to find a commune's BFS
    /// number.
    #[tool(
        title = "List communes",
        annotations(
            title = "List communes",
            read_only_hint = true,
            destructive_hint = false,
            idempotent_hint = true,
            open_world_hint = false
        )
    )]
    async fn list_communes(&self) -> Result<CallToolResult, ErrorData> {
        let started = Instant::now();
        let list = communes::list(&self.state.db).await.map_err(internal)?;
        self.count("list_communes", started, 200, None);
        Ok(CallToolResult::structured(json!({ "result": list })))
    }
}

#[tool_handler(
    name = "opencommune",
    instructions = "OpenCommune is an open archive of the documents Swiss communes publish on their websites: minutes, decisions, budgets, accounts, vote results and other papers of assemblies, parliaments and councils. Each file is listed once, with a fixed label and a link to the original on the commune's website. Use list_communes to see coverage and to find a commune's BFS number, search_documents to filter documents by commune, section type, kind, body, year and label, and get_document for one document. Kinds, bodies, dates and sections come from an automatic classification by a language model that no person has checked yet. Coverage is partial and growing: no result does not mean that no document exists."
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
