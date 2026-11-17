//! MCP server over streamable HTTP at `/mcp`: the commune list, the document search, one document,
//! the full-text search and the page reader, on the same queries as the REST API. Stateless: every
//! request is answered on its own, no session is kept.

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
use crate::db::fulltext::{self, PageRange, TextSearch, UNAVAILABLE};
use crate::usage::Hit;

const SEARCH_DESCRIPTION: &str = "Search the archive's documents, newest first. Every filter is \
optional; filters combine with AND. `commune`: a BFS number from list_communes. `section`: \
documents with at least one section of this type (minutes, decisions, vote_result, budget, \
accounts, invitation_agenda, proposal, member_request, regulation, report, notice, plan_or_map, \
news, other, unclear). `family`: documents with at least one section of this family \
(deliberation, money, proposals, rules, information, other). `body`: parliament, \
citizens_assembly, executive, commission, commune, other_public_body, private or unknown. `year`: \
the year of the document's date, else the one year the classifier read, else the year of the \
commune's listing date. `q`: text the document's title contains, ignoring case (and accents from \
3 characters on); search_text searches the text of the pages. `limit` 0 to 100 (default 20) \
and `offset` page through the results. Returns `total`, `facets` (documents per \
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

const SEARCH_TEXT_DESCRIPTION: &str = "Search the text of the pages, best match first. The search \
covers the pages inside sections of these types: minutes, decisions, vote_result, budget, \
accounts, proposal, invitation_agenda and member_request; pages without a text layer come in as \
OCR reaches them. `q`: every word must occur on the page; \"a phrase\" in double quotes must \
occur as written; a word ending in * matches the words that begin with it (at least 3 letters \
before the *); German compounds need the *: Kunstrasen* also finds Kunstrasenplatz. Case and \
accents do not matter; there are no operators. Filters, all optional, combine with AND: \
`commune` (a BFS number from list_communes), `canton` (such as ZH), `year`, `from` and `to` (the \
document's date, YYYY-MM-DD, inclusive), `section` and `family` (only pages inside a section of \
that type or family match), `body`, `document` (a sha256: search inside that one document). \
`limit` 0 to 50 (default 10) and `offset` page through the documents; `pages_per_document` 1 to \
20 (default 3) sets how many matching pages each document shows. Returns `total` (documents), `facets` (documents per year, section type, canton, and \
the 20 communes with the most), and `items`: documents as in search_documents, each with \
`matching_pages` and `pages`, its best pages: `page`, `section_types`, `snippet` (plain text: \
one or two passages that show as many of the matched words as fit), `highlights` (the matches in the snippet as [start, end) character \
ranges) and `original_url` (opens the file at that page). The search ranks at most the 20,000 \
best matching pages; when more match, `capped` is true and the total and the facets count only \
the documents of those pages. Next, read the pages around a hit with read_pages and cite the \
document and the page. The page text is machine-extracted (the PDF's text layer, or OCR) and no \
person has checked yet whether it is complete or right; titles, dates and sections come from an \
automatic classification. Names, street addresses and e-mail addresses in the text are replaced \
by the marks ［name］, ［address］ and ［email］ (［secret］ for passwords and keys), dates of birth \
and mobile numbers by ［date］ and ［phone］.";

const READ_PAGES_DESCRIPTION: &str = "Read the text of up to 10 pages of one document: `sha256` \
(from search_text or search_documents), `from` (default 1) and `to` (default from + 9). Returns \
`page_count` and per page `page`, `section_types`, `source` (layer: the PDF's text layer; ocr: \
text recognition on the page image), `text` and `original_url` (opens the file at that page). A \
page outside the search has no text and a `reason` instead. The text is machine-extracted: \
reading order, tables and hyphenation can be off, and no person has checked yet whether it is \
complete or right. Names, street addresses and e-mail addresses are replaced by the marks ［name］, \
［address］ and ［email］, dates of birth and mobile numbers by ［date］ and ［phone］. Cite the page \
and its original_url.";

#[derive(Deserialize, JsonSchema)]
#[schemars(crate = "rmcp::schemars")]
pub struct ReadPagesArgs {
    /// The document's sha256, from search_text or search_documents.
    sha256: String,
    /// The first page to read; 1, the default, is the first page of the file.
    #[serde(default)]
    from: Option<i64>,
    /// The last page to read; at most 10 pages from `from` on. Default: from + 9.
    #[serde(default)]
    to: Option<i64>,
}

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
                bot: None,
                status,
                duration_ms: started.elapsed().as_secs_f64() * 1000.0,
                search_total,
                visitor: None,
                referrer: None,
            });
        }
    }
}

fn internal(error: sqlx::Error) -> ErrorData {
    tracing::error!(%error, "database query failed");
    ErrorData::internal_error("database query failed", None)
}

/// A tool error the agent can read and act on.
fn refused(tool: &str, reason: &str) -> CallToolResult {
    CallToolResult::error(vec![ContentBlock::text(format!(
        "Error executing tool {tool}: {reason}"
    ))])
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
            return Ok(refused("search_documents", &reason));
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

    #[tool(
        title = "Search the text of pages",
        description = SEARCH_TEXT_DESCRIPTION,
        annotations(
            title = "Search the text of pages",
            read_only_hint = true,
            destructive_hint = false,
            idempotent_hint = true,
            open_world_hint = false
        )
    )]
    async fn search_text(
        &self,
        Parameters(search): Parameters<TextSearch>,
    ) -> Result<CallToolResult, ErrorData> {
        let started = Instant::now();
        if !self.state.fulltext {
            self.count("search_text", started, 503, None);
            return Ok(refused("search_text", UNAVAILABLE));
        }
        let query = match search.check() {
            Ok(query) => query,
            Err(reason) => {
                self.count("search_text", started, 400, None);
                return Ok(refused("search_text", &reason));
            }
        };
        let page = fulltext::search(&self.state.db, &search, &query)
            .await
            .map_err(internal)?;
        let total = (search.offset == 0).then_some(page.total);
        self.count("search_text", started, 200, total);
        Ok(CallToolResult::structured(
            serde_json::to_value(page).unwrap_or(Value::Null),
        ))
    }

    #[tool(
        title = "Read pages",
        description = READ_PAGES_DESCRIPTION,
        annotations(
            title = "Read pages",
            read_only_hint = true,
            destructive_hint = false,
            idempotent_hint = true,
            open_world_hint = false
        )
    )]
    async fn read_pages(
        &self,
        Parameters(args): Parameters<ReadPagesArgs>,
    ) -> Result<CallToolResult, ErrorData> {
        let started = Instant::now();
        if !self.state.fulltext {
            self.count("read_pages", started, 503, None);
            return Ok(refused("read_pages", UNAVAILABLE));
        }
        let range = PageRange {
            from: args.from,
            to: args.to,
        };
        let (from, to) = match range.check() {
            Ok(range) => range,
            Err(reason) => {
                self.count("read_pages", started, 400, None);
                return Ok(refused("read_pages", &reason));
            }
        };
        let pages = fulltext::read(&self.state.db, &args.sha256, from, to)
            .await
            .map_err(internal)?;
        let Some(pages) = pages else {
            self.count("read_pages", started, 404, None);
            return Ok(refused("read_pages", "no document has this sha256"));
        };
        self.count("read_pages", started, 200, None);
        Ok(CallToolResult::structured(
            serde_json::to_value(pages).unwrap_or(Value::Null),
        ))
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
    name = "tractanda",
    instructions = "Tractanda is an open archive of the documents Swiss communes publish on their websites: minutes, decisions, budgets, accounts, vote results and other papers of assemblies, parliaments and councils. Each file is listed once, with a fixed label and a link to the original on the commune's website. Use list_communes to see coverage and to find a commune's BFS number, search_documents to filter documents by commune, section type, kind, body, year and label, and get_document for one document. To find what the pages say, use search_text, then read the pages around a hit with read_pages, then cite the document and the page: each page has an original_url that opens the file at that page. The page text is machine-extracted (the PDF's text layer, or OCR) and no person has checked it: quote it with care and point to the page. Names, street addresses and e-mail addresses in the page text are replaced by ［name］, ［address］ and ［email］. Kinds, bodies, dates and sections come from an automatic classification by a language model that no person has checked yet. Coverage is partial and growing: no result does not mean that no document exists."
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
