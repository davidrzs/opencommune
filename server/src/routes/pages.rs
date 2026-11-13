//! The pages search engines and AI assistants read (`site.rs`): `robots.txt`, `sitemap.xml`,
//! `llms.txt`, and the HTML of the start, commune, decision, about and search pages.

use axum::extract::State;
use axum::http::{StatusCode, header};
use axum::response::{Html, IntoResponse, Redirect, Response};
use serde_json::json;

use crate::AppState;
use crate::db::{decisions, pages};
use crate::error::ApiError;
use crate::models::ArchiveCommune;
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

const DATASET: &str = "https://huggingface.co/datasets/davidrzs/opencommune";
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

/// Every page in every language. One file holds at most 50,000 addresses; past that the sitemap
/// needs an index.
pub async fn sitemap(State(state): State<AppState>) -> Result<Response, ApiError> {
    let (communes, decisions) = pages::sitemap(&state.db).await?;
    let mut paths = vec![
        String::new(),
        "/ueber-uns".to_string(),
        "/datenschutz".to_string(),
    ];
    paths.extend(communes.iter().map(|id| format!("/gemeinden/{id}")));
    paths.extend(decisions.iter().map(|id| format!("/entscheide/{id}")));
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
    let body = format!(
        "# OpenCommune\n\n\
         > Open archive of the decisions of Swiss municipalities: minutes and decisions of communal \
         assemblies, parliaments and councils in German, French and Italian, collected from the \
         communes' own websites, structured with a language model and anonymised. Free to use \
         under CC0 1.0; a citation (\"OpenCommune, {base}\") is appreciated.\n\n\
         The archive holds {} decisions from {} communes and lists {} documents from {} communes \
         with links to the originals. It is growing: a missing document does not mean that a \
         meeting did not take place. Decisions are extracted by a language model and not checked \
         one by one; each links to its source PDF and page.\n\n\
         ## Query it\n\n\
         - [MCP server]({base}/mcp): streamable HTTP, no key. Tools: `search_decisions` (full text, \
         filters by commune, canton, category, outcome, date and amount), `get_decision`, \
         `list_communes`.\n\
         - [JSON API]({SOURCE}/blob/main/server/API.md): for example \
         `{base}/api/decisions?q=Schulhaus`, `{base}/api/decisions/{{id}}`, \
         `{base}/api/archive/communes`.\n\n\
         ## Pages\n\n\
         - A commune: `{base}/de/gemeinden/{{BFS number}}`, also in French (`/fr/`) and Italian \
         (`/it/`).\n\
         - A decision: `{base}/de/entscheide/{{id}}`.\n\
         - [Sitemap]({base}/sitemap.xml), [about]({base}/de/ueber-uns).\n\n\
         ## Data and code\n\n\
         - [Dataset on Hugging Face]({DATASET})\n\
         - [Source code]({SOURCE}) (MIT)\n\
         - Contact: zdavid@ethz.ch\n",
        n(t.decisions),
        n(t.decision_communes),
        n(t.documents),
        n(t.document_communes),
    );
    Ok(text("text/markdown; charset=utf-8", body))
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
            ("decisions", lang.number(t.decisions)),
            ("decision_communes", lang.number(t.decision_communes)),
            ("documents", lang.number(t.documents)),
            ("document_communes", lang.number(t.document_communes)),
        ],
    );
    let mut facts = format!(
        "<h1>OpenCommune</h1><p>{}</p><p>{}</p><h2>{}</h2><ul>",
        escape(w.site),
        escape(&totals),
        escape(w.with_decisions)
    );
    for c in pages::communes_with_decisions(&state.db).await? {
        facts.push_str(&format!(
            "<li><a href=\"/{}/gemeinden/{}\">{} ({})</a></li>",
            lang.code(),
            c.bfs_id,
            escape(&c.name),
            escape(&c.canton)
        ));
    }
    facts.push_str(&format!(
        "</ul><p><a href=\"/{}/ueber-uns\">{}</a> · <a href=\"/llms.txt\">llms.txt</a> · \
         <a href=\"{DATASET}\">Hugging Face</a></p>",
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
            "sameAs": [DATASET, SOURCE],
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
    let Some((commune, recent)) = found else {
        return Ok(not_found(&state, lang, path).await);
    };
    let (bfs_id, name, canton, website, documents, decisions) = match &commune {
        ArchiveCommune::Covered { commune: c, .. } => (
            c.bfs_id,
            c.name.as_str(),
            c.canton.as_str(),
            Some(c.website.as_str()).filter(|w| !w.is_empty()),
            c.documents,
            c.decisions,
        ),
        ArchiveCommune::RegisterOnly {
            bfs_id,
            name,
            canton,
            website,
            documents,
            decisions,
            ..
        } => (
            *bfs_id,
            name.as_str(),
            canton.as_str(),
            website.as_deref(),
            *documents,
            *decisions,
        ),
    };
    let w = lang.words();
    let line = fill(
        w.commune_line,
        &[
            ("name", name.to_string()),
            ("canton", canton.to_string()),
            ("documents", lang.number(documents)),
            ("decisions", lang.number(decisions)),
        ],
    );
    let mut facts = format!("<h1>{}</h1><p>{}</p>", escape(name), escape(&line));
    if let Some(site) = website {
        facts.push_str(&format!(
            "<p><a href=\"{}\">{}</a></p>",
            escape(site),
            escape(w.website)
        ));
    }
    if !recent.is_empty() {
        facts.push_str(&format!("<h2>{}</h2><ul>", escape(w.recent)));
        for d in &recent {
            facts.push_str(&format!(
                "<li>{}<a href=\"/{}/entscheide/{}\">{}</a></li>",
                d.meeting_date
                    .as_deref()
                    .map(|day| format!("{}: ", date(day)))
                    .unwrap_or_default(),
                lang.code(),
                escape(&d.id),
                escape(&d.title)
            ));
        }
        facts.push_str("</ul>");
    }
    let mut place = json!({
        "@context": "https://schema.org",
        "@type": "AdministrativeArea",
        "name": name,
        "identifier": {"@type": "PropertyValue", "propertyID": "BFS", "value": bfs_id},
        "containedInPlace": {"@type": "AdministrativeArea", "name": canton},
        "url": state.site.url(lang, &path),
    });
    if let Some(site) = website {
        place["sameAs"] = json!(site);
    }
    let page = Page {
        lang,
        title: format!("{name} — OpenCommune"),
        description: line,
        path,
        json_ld: Some(place),
        facts,
        noindex: false,
    };
    Ok(html(&state, StatusCode::OK, &page).await)
}

pub async fn decision(state: AppState, lang: Lang, id: String) -> Result<Response, ApiError> {
    let path = format!("/entscheide/{id}");
    let Some(d) = decisions::get(&state.db, &id).await? else {
        return Ok(not_found(&state, lang, path).await);
    };
    let w = lang.words();
    let mut meta = vec![format!(
        "<a href=\"/{}/gemeinden/{}\">{} ({})</a>",
        lang.code(),
        d.commune.bfs_id,
        escape(&d.commune.name),
        escape(&d.commune.canton)
    )];
    if let Some(day) = &d.meeting_date {
        meta.push(date(day));
    }
    if let Some(outcome) = d.outcome.as_deref().and_then(|o| w.outcome(o)) {
        meta.push(outcome.to_string());
    }
    if let Some(amount) = d.amount_chf {
        meta.push(format!("CHF {}", lang.number(amount.round() as i64)));
    }
    let facts = format!(
        "<h1>{}</h1><p>{}</p><p>{}</p><p><a href=\"{}\">{}</a></p>",
        escape(&d.title),
        meta.join(" · "),
        escape(&d.summary),
        escape(&d.source_link),
        escape(&fill(w.source, &[("page", d.page_start.to_string())]))
    );
    let page = Page {
        lang,
        title: format!("{} — {} — OpenCommune", d.title, d.commune.name),
        description: shorten(&d.summary, 300),
        path,
        json_ld: None,
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
            "<h1>{}</h1><p>{}</p><p>{}</p><p><a href=\"{SOURCE}\">GitHub</a> · \
             <a href=\"{DATASET}\">Hugging Face</a></p>",
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

/// At most `max` characters, cut at a word and marked with an ellipsis.
fn shorten(text: &str, max: usize) -> String {
    if text.chars().count() <= max {
        return text.to_string();
    }
    let cut: String = text.chars().take(max).collect();
    let cut = cut.rsplit_once(' ').map_or(cut.as_str(), |(head, _)| head);
    format!("{}…", cut.trim_end_matches([',', ';', ':', '.']))
}

/// The text before the first colon: the start page's title.
fn first_clause(text: &str) -> &str {
    text.split([':', '：']).next().unwrap_or(text).trim()
}

#[cfg(test)]
mod tests {
    use super::{fill, first_clause, shorten};

    #[test]
    fn helpers() {
        assert_eq!(
            fill("{a} und {b}", &[("a", "1".into()), ("b", "2".into())]),
            "1 und 2"
        );
        assert_eq!(shorten("eins zwei drei", 9), "eins…");
        assert_eq!(shorten("kurz", 9), "kurz");
        assert_eq!(first_clause("Offenes Archiv: Protokolle"), "Offenes Archiv");
    }
}
