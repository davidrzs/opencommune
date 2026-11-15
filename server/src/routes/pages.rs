//! The pages search engines and AI assistants read (`site.rs`): `robots.txt`, `sitemap.xml`,
//! `llms.txt`, and the HTML of the start, commune, about, privacy and search pages.

use axum::extract::State;
use axum::http::{StatusCode, header};
use axum::response::{Html, IntoResponse, Redirect, Response};
use serde_json::json;

use crate::AppState;
use crate::db::pages;
use crate::error::ApiError;
use crate::site::{Lang, Page, date, escape};

/// Crawlers that collect training data. They may read nothing; search engines and the assistants'
/// search and on-request fetchers may read the pages.
const TRAINING_CRAWLERS: [&str; 9] = [
    "GPTBot",
    "ClaudeBot",
    "anthropic-ai",
    "CCBot",
    "Google-Extended",
    "Applebot-Extended",
    "Meta-ExternalAgent",
    "Bytespider",
    "cohere-ai",
];

const SOURCE: &str = "https://github.com/davidrzs/opencommune";

pub async fn robots(State(state): State<AppState>) -> Response {
    let mut body = String::from(
        "# Search engines and AI search assistants may read the pages; crawlers that collect\n\
         # training data may not. The API and the MCP server are for direct use.\n",
    );
    for bot in TRAINING_CRAWLERS {
        body.push_str(&format!("User-agent: {bot}\n"));
    }
    body.push_str("Disallow: /\n\nUser-agent: *\n");
    for path in ["/api/", "/mcp", "/original/"] {
        body.push_str(&format!("Disallow: {path}\n"));
    }
    for lang in Lang::ALL {
        body.push_str(&format!("Disallow: /{}/suche\n", lang.code()));
    }
    body.push_str("Allow: /\n");
    if state.site.indexing {
        body.push_str(&format!(
            "\nSitemap: {}/sitemap.xml\n",
            state.site.public_url
        ));
    }
    text("text/plain; charset=utf-8", body)
}

/// Every page in every language: the start, about and privacy pages and every commune. One file
/// holds at most 50,000 addresses; past that the sitemap needs an index.
pub async fn sitemap(State(state): State<AppState>) -> Result<Response, ApiError> {
    let communes = pages::sitemap(&state.db).await?;
    let mut paths = vec![
        String::new(),
        "/ueber-uns".to_string(),
        "/datenschutz".to_string(),
    ];
    paths.extend(communes.iter().map(|id| format!("/gemeinden/{id}")));
    let mut xml = String::from(
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n\
         <urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">\n",
    );
    for path in &paths {
        for lang in Lang::ALL {
            xml.push_str(&format!(
                "<url><loc>{}</loc></url>\n",
                escape(&state.site.url(lang, path))
            ));
        }
    }
    xml.push_str("</urlset>\n");
    Ok(text("application/xml; charset=utf-8", xml))
}

/// A short Markdown guide for AI agents (llmstxt.org): what the archive is and how to query it.
pub async fn llms(State(state): State<AppState>) -> Result<Response, ApiError> {
    let t = pages::totals(&state.db).await?;
    let base = &state.site.public_url;
    let n = |v| Lang::De.number(v);
    let (text_tools, search) = if state.fulltext {
        (", `search_text`, `read_pages`", llms_search(base))
    } else {
        ("", String::new())
    };
    let body = format!(
        "# OpenCommune\n\n\
         > Open archive of the documents Swiss municipalities publish on their websites: minutes, \
         decisions, budgets, accounts, vote results and other papers of communal assemblies, \
         parliaments and councils. Each file is listed once, with its title and a link to the \
         original on the commune's website. Free to use under CC0 1.0; a citation \
         (\"OpenCommune, {base}\") is appreciated.\n\n\
         The archive lists {} documents from {} communes, each classified by a language model: \
         its title and body as printed, the kind of body, its date and years, its languages and \
         its sections (minutes, decisions, vote results, budget, accounts and others) with their \
         pages. No person has checked this classification yet. The archive is growing: a missing \
         document does not mean that a meeting did not take place.\n\n\
         ## Query it\n\n\
         - [MCP server]({base}/mcp): streamable HTTP, no key. Tools: `search_documents` (filters by \
         commune, section type, section family, body, year and title, with counts per value), \
         `get_document`, `list_communes`{text_tools}.\n\
         - [JSON API]({SOURCE}/blob/main/server/API.md): for example \
         `{base}/api/documents?commune=261&section=budget`, `{base}/api/documents/{{sha256}}`, \
         `{base}/api/communes`; described in `{base}/api/openapi.json`.\n\n\
         {search}\
         ## Pages\n\n\
         - A commune: `{base}/de/gemeinden/{{BFS number}}`, also in French (`/fr/`) and Italian \
         (`/it/`).\n\
         - [Sitemap]({base}/sitemap.xml), [about]({base}/de/ueber-uns).\n\n\
         ## Code\n\n\
         - [Source code]({SOURCE}) (MIT)\n\
         - Contact: zdavid@ethz.ch\n",
        n(t.documents),
        n(t.communes),
    );
    Ok(text("text/markdown; charset=utf-8", body))
}

/// The part of `llms.txt` on the full-text search, for a server with the index.
fn llms_search(base: &str) -> String {
    format!(
        "## Search the text of the pages\n\n\
         - `{base}/api/pages?q=Kunstrasen*%20Kredit&canton=ZH` (MCP: `search_text`): the documents \
         whose pages hold every word, best first, each with its best pages as plain-text snippets \
         and a link to the file at that page. `\"a phrase\"` must occur as written; `word*` matches \
         the words that begin with it (at least 3 letters before the `*`), which German compounds \
         need: `Kunstrasen*` also finds `Kunstrasenplatz`. Case and accents do not matter; there \
         are no operators. Filters: `commune` (BFS number), `canton`, `year`, `from` and `to` \
         (YYYY-MM-DD), `section`, `family`, `body`, and `document` (a sha256: search inside one \
         document). `limit` up to 50, `offset`, and `pages_per_document` 1 to 20 (default 3).\n\
         - The search ranks at most the 20,000 best matching pages. When more match, `capped` is \
         true and `total` and the facets count only those pages' documents: add a word or a \
         filter.\n\
         - `{base}/api/documents/{{sha256}}/pages?from=1&to=10` (MCP: `read_pages`): the text of up \
         to 10 pages at a time. An `original_url` is relative to {base} and redirects to the \
         commune's file at that page.\n\
         - The search covers the pages inside sections of these types: minutes, decisions, \
         vote_result, budget, accounts, proposal, invitation_agenda and member_request. It leaves \
         out bulletins and the documents of private bodies; pages without a text layer come in as \
         OCR reaches them.\n\
         - The text is machine-extracted (the PDF's text layer, or OCR) and no person has checked \
         it. Names, street addresses and e-mail addresses are replaced by `［name］`, `［address］` \
         and `［email］`. Cite the document and the page.\n\n"
    )
}

/// The front end chooses the language; the start page without one is the German one.
pub async fn root() -> Redirect {
    Redirect::temporary("/de")
}

pub async fn home(state: AppState, lang: Lang) -> Result<Response, ApiError> {
    let w = lang.words();
    let t = pages::totals(&state.db).await?;
    let totals = fill(
        w.totals,
        &[
            ("documents", lang.number(t.documents)),
            ("communes", lang.number(t.communes)),
        ],
    );
    let mut facts = format!(
        "<h1>OpenCommune</h1><p>{}</p><p>{}</p><h2>{}</h2><ul>",
        escape(w.site),
        escape(&totals),
        escape(w.with_documents)
    );
    for c in pages::communes_with_documents(&state.db).await? {
        facts.push_str(&format!(
            "<li><a href=\"/{}/gemeinden/{}\">{} ({})</a></li>",
            lang.code(),
            c.bfs_id,
            escape(&c.name),
            escape(&c.canton)
        ));
    }
    facts.push_str(&format!(
        "</ul><p><a href=\"/{}/ueber-uns\">{}</a> · <a href=\"/llms.txt\">llms.txt</a></p>",
        lang.code(),
        escape(w.about)
    ));
    let page = Page {
        lang,
        path: String::new(),
        title: format!("OpenCommune — {}", first_clause(w.site)),
        description: w.site.to_string(),
        json_ld: Some(json!({
            "@context": "https://schema.org",
            "@type": "Dataset",
            "name": "OpenCommune",
            "description": w.site,
            "url": state.site.url(lang, ""),
            "license": "https://creativecommons.org/publicdomain/zero/1.0/",
            "isAccessibleForFree": true,
            "inLanguage": ["de", "fr", "it"],
            "spatialCoverage": {"@type": "Place", "name": "Switzerland"},
            "creator": {"@type": "Person", "name": "David Zollikofer"},
            "sameAs": [SOURCE],
        })),
        facts,
        noindex: false,
    };
    Ok(html(&state, StatusCode::OK, &page).await)
}

pub async fn commune(state: AppState, lang: Lang, id: String) -> Result<Response, ApiError> {
    let path = format!("/gemeinden/{id}");
    let found = match id.parse::<i64>() {
        Ok(bfs_id) if bfs_id > 0 => pages::commune(&state.db, bfs_id).await?,
        _ => None,
    };
    let Some((c, documents)) = found else {
        return Ok(not_found(&state, lang, path).await);
    };
    let w = lang.words();
    let line = fill(
        w.commune_line,
        &[
            ("name", c.name.clone()),
            ("canton", c.canton.clone()),
            ("documents", lang.number(c.documents)),
        ],
    );
    let website = c.website.as_deref().filter(|w| !w.is_empty());
    let mut facts = format!("<h1>{}</h1><p>{}</p>", escape(&c.name), escape(&line));
    if let Some(site) = website {
        facts.push_str(&format!(
            "<p><a href=\"{}\">{}</a></p>",
            escape(site),
            escape(w.website)
        ));
    }
    if !documents.facets.years.is_empty() {
        let years: Vec<String> = documents
            .facets
            .years
            .iter()
            .map(|y| {
                let year = y.value.map_or(w.no_year.to_string(), |v| v.to_string());
                format!("{year}: {}", lang.number(y.count))
            })
            .collect();
        facts.push_str(&format!(
            "<h2>{}</h2><p>{}</p>",
            escape(w.by_year),
            escape(&years.join(" · "))
        ));
    }
    if !documents.items.is_empty() {
        facts.push_str(&format!("<h2>{}</h2><ul>", escape(w.recent)));
        for d in &documents.items {
            let day = d.date.as_deref().or(d.listing_date.as_deref());
            facts.push_str(&format!(
                "<li>{}<a href=\"{}?commune={}\">{}</a></li>",
                day.map(|day| format!("{}: ", date(day)))
                    .unwrap_or_default(),
                escape(&d.original_url),
                c.bfs_id,
                escape(d.title.as_deref().unwrap_or(w.untitled))
            ));
        }
        facts.push_str("</ul>");
    }
    let mut place = json!({
        "@context": "https://schema.org",
        "@type": "AdministrativeArea",
        "name": c.name,
        "identifier": {"@type": "PropertyValue", "propertyID": "BFS", "value": c.bfs_id},
        "containedInPlace": {"@type": "AdministrativeArea", "name": c.canton},
        "url": state.site.url(lang, &path),
    });
    if let Some(site) = website {
        place["sameAs"] = json!(site);
    }
    let page = Page {
        lang,
        title: format!("{} — OpenCommune", c.name),
        description: line,
        path,
        json_ld: Some(place),
        facts,
        noindex: false,
    };
    Ok(html(&state, StatusCode::OK, &page).await)
}

pub async fn about(state: AppState, lang: Lang) -> Response {
    let w = lang.words();
    let page = Page {
        lang,
        path: "/ueber-uns".to_string(),
        title: format!("{} — OpenCommune", w.about),
        description: w.about_text.to_string(),
        json_ld: None,
        facts: format!(
            "<h1>{}</h1><p>{}</p><p>{}</p><p><a href=\"{SOURCE}\">GitHub</a></p>",
            escape(w.about),
            escape(w.about_text),
            escape(w.site)
        ),
        noindex: false,
    };
    html(&state, StatusCode::OK, &page).await
}

pub async fn privacy(state: AppState, lang: Lang) -> Response {
    let w = lang.words();
    let page = Page {
        lang,
        path: "/datenschutz".to_string(),
        title: format!("{} — OpenCommune", w.privacy),
        description: w.privacy_text.to_string(),
        json_ld: None,
        facts: format!(
            "<h1>{}</h1><p>{}</p><p><a href=\"mailto:zdavid@ethz.ch\">zdavid@ethz.ch</a></p>",
            escape(w.privacy),
            escape(w.privacy_text)
        ),
        noindex: false,
    };
    html(&state, StatusCode::OK, &page).await
}

/// Search results are never indexed: the page carries only its title.
pub async fn search(state: AppState, lang: Lang) -> Response {
    let w = lang.words();
    let page = Page {
        lang,
        path: "/suche".to_string(),
        title: format!("{} — OpenCommune", w.search),
        description: w.site.to_string(),
        json_ld: None,
        facts: format!("<h1>{}</h1>", escape(w.search)),
        noindex: true,
    };
    html(&state, StatusCode::OK, &page).await
}

async fn not_found(state: &AppState, lang: Lang, path: String) -> Response {
    let page = Page {
        lang,
        path,
        title: "OpenCommune".to_string(),
        description: lang.words().site.to_string(),
        json_ld: None,
        facts: String::new(),
        noindex: true,
    };
    html(state, StatusCode::NOT_FOUND, &page).await
}

async fn html(state: &AppState, status: StatusCode, page: &Page) -> Response {
    let shell = state.site.shell().await;
    (status, Html(state.site.render(&shell, page))).into_response()
}

fn text(content_type: &'static str, body: String) -> Response {
    ([(header::CONTENT_TYPE, content_type)], body).into_response()
}

/// `{key}` in `template` replaced by the values.
fn fill(template: &str, values: &[(&str, String)]) -> String {
    values
        .iter()
        .fold(template.to_string(), |text, (key, value)| {
            text.replace(&format!("{{{key}}}"), value)
        })
}

/// The text before the first colon: the start page's title.
fn first_clause(text: &str) -> &str {
    text.split([':', '：']).next().unwrap_or(text).trim()
}

#[cfg(test)]
mod tests {
    use super::{fill, first_clause};

    #[test]
    fn helpers() {
        assert_eq!(
            fill("{a} und {b}", &[("a", "1".into()), ("b", "2".into())]),
            "1 und 2"
        );
        assert_eq!(first_clause("Offenes Archiv: Protokolle"), "Offenes Archiv");
    }
}
