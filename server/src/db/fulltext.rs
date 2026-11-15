//! Full-text search over page text: the search with its facets, and the text of a range of pages.
//!
//! The index is `fulltext.db` (`src/opencommune/fulltext.py`), attached to every connection as the
//! schema `fulltext`: `pages (id, sha256, page, source, run)` and `page_fts`, an FTS5 table whose
//! rowid is `pages.id`. Section types, communes, years, bodies and dates come from the serving
//! database, joined on sha256 and page.

use std::collections::{HashMap, HashSet};

use rmcp::schemars::JsonSchema;
use serde::Deserialize;
use sqlx::{FromRow, QueryBuilder, Sqlite, SqlitePool};

use super::documents::{self, text};
use crate::models::{
    CommuneCount, Count, Document, DocumentPages, PageHit, PageText, Section, TextDocument,
    TextFacets, TextPage, page_url,
};

/// What the full-text endpoints and tools answer when the server has no index.
pub const UNAVAILABLE: &str = "Full-text search is not available on this server: it has no \
full-text index.";

pub const DEFAULT_LIMIT: i64 = 10;
pub const MAX_LIMIT: i64 = 50;
/// The most matching pages a search ranks. A common word matches hundreds of thousands of pages;
/// ranking them all takes seconds. The documents, the total and the facets come from these pages.
pub const CAP: i64 = 20_000;
/// The most pages the page reader returns at once.
pub const MAX_PAGES: i64 = 10;
/// The most words and phrases in a query, and the longest query in characters.
const MAX_TERMS: usize = 10;
const MAX_QUERY_CHARS: usize = 500;
/// The fewest letters or digits before `*`. A shorter prefix stands for too many words.
const MIN_PREFIX: usize = 3;
/// A snippet: the words FTS5 picks around the matches (about 300 characters), and the most
/// characters kept.
const SNIPPET_WORDS: i64 = 40;
const SNIPPET_CHARS: usize = 360;
/// The marks FTS5 puts around a match in a snippet. Page text does not contain these sequences.
const OPEN: &str = "\u{1}\u{2}";
const CLOSE: &str = "\u{2}\u{1}";

/// The parameters of `GET /api/pages` and of the MCP tool `search_text`. The filters are optional
/// and combine with AND; a blank text filter is no filter.
#[derive(Deserialize, JsonSchema)]
#[schemars(crate = "rmcp::schemars")]
pub struct TextSearch {
    /// The words to find in the page text. Every word must occur on the page; "a phrase" in
    /// double quotes must occur as written; a word ending in * matches the words that begin with
    /// it (at least 3 letters before the *). Case and accents do not matter. No operators.
    pub q: String,
    /// A commune's BFS number: the documents it links.
    #[serde(default)]
    pub commune: Option<i64>,
    /// A canton's code, such as ZH: the documents of its communes.
    #[serde(default)]
    pub canton: Option<String>,
    /// The document's year.
    #[serde(default)]
    pub year: Option<i64>,
    /// The earliest date (YYYY-MM-DD) of the document: its date, else the commune's listing date.
    #[serde(default)]
    pub from: Option<String>,
    /// The latest date (YYYY-MM-DD) of the document, inclusive.
    #[serde(default)]
    pub to: Option<String>,
    /// A section type: only pages inside a section of this type match.
    #[serde(default)]
    pub section: Option<String>,
    /// A section family: only pages inside a section of this family match.
    #[serde(default)]
    pub family: Option<String>,
    /// The kind of body behind the document.
    #[serde(default)]
    pub body: Option<String>,
    /// Documents to skip.
    #[serde(default)]
    pub offset: i64,
    /// Documents to return, 0 to 50.
    #[serde(default = "default_limit")]
    pub limit: i64,
}

fn default_limit() -> i64 {
    DEFAULT_LIMIT
}

impl TextSearch {
    /// The query as FTS5 reads it, or why the parameters are refused.
    pub fn check(&self) -> Result<Query, String> {
        if self.offset < 0 {
            return Err("offset must not be negative".into());
        }
        if !(0..=MAX_LIMIT).contains(&self.limit) {
            return Err(format!("limit must be between 0 and {MAX_LIMIT}"));
        }
        for (name, value) in [("from", &self.from), ("to", &self.to)] {
            if text(value).is_some_and(|v| !is_date(v)) {
                return Err(format!("{name} must be a date: YYYY-MM-DD"));
            }
        }
        Query::parse(&self.q)
    }
}

/// `YYYY-MM-DD`, digits where the digits go.
fn is_date(value: &str) -> bool {
    let b = value.as_bytes();
    b.len() == 10
        && b.iter().enumerate().all(|(i, c)| {
            if i == 4 || i == 7 {
                *c == b'-'
            } else {
                c.is_ascii_digit()
            }
        })
}

/// A search query as an FTS5 expression. Every word and phrase of the input is one quoted FTS5
/// string, so nothing a user types is read as FTS5 syntax.
pub struct Query(String);

impl Query {
    /// Reads the search box's syntax: words, "phrases" and prefixes (`word*`, `"a phrase"*`).
    /// A word without a letter or a digit is left out. An unclosed quote runs to the end.
    pub fn parse(input: &str) -> Result<Query, String> {
        if input.chars().count() > MAX_QUERY_CHARS {
            return Err(format!("q is longer than {MAX_QUERY_CHARS} characters"));
        }
        let mut terms = Vec::new();
        let mut chars = input.chars().peekable();
        while let Some(&first) = chars.peek() {
            if first.is_whitespace() {
                chars.next();
                continue;
            }
            let mut term = String::new();
            let mut prefix = false;
            if first == '"' {
                chars.next();
                term.extend(chars.by_ref().take_while(|c| *c != '"'));
                while chars.next_if_eq(&'*').is_some() {
                    prefix = true;
                }
            } else {
                while let Some(c) = chars.next_if(|c| !c.is_whitespace() && *c != '"') {
                    term.push(c);
                }
                while term.ends_with('*') {
                    term.pop();
                    prefix = true;
                }
            }
            let Some(last) = term
                .split(|c: char| !c.is_alphanumeric())
                .rfind(|w| !w.is_empty())
            else {
                continue;
            };
            if prefix && last.chars().count() < MIN_PREFIX {
                return Err(format!(
                    "a word before * needs at least {MIN_PREFIX} letters or digits"
                ));
            }
            let star = if prefix { "*" } else { "" };
            terms.push(format!("\"{}\"{star}", term.replace('"', "\"\"")));
        }
        if terms.is_empty() {
            return Err("q has no word to search for".into());
        }
        if terms.len() > MAX_TERMS {
            return Err(format!("q has more than {MAX_TERMS} words and phrases"));
        }
        Ok(Query(terms.join(" ")))
    }
}

/// A row of the search's summary: a count, a facet value, a document or a page.
#[derive(FromRow)]
struct Summary {
    kind: String,
    number: Option<i64>,
    text: Option<String>,
    name: Option<String>,
    n: i64,
    score: Option<f64>,
}

/// The query up to the matching pages: `hit` holds the best `CAP` pages that match and pass the
/// filters, `doc` their documents with the best score and the number of pages, `item` the
/// documents of the requested page of results.
fn push_hits(qb: &mut QueryBuilder<Sqlite>, s: &TextSearch, query: &Query) {
    qb.push(
        "WITH hit AS MATERIALIZED (SELECT p.id, p.sha256, p.page, f.rank AS score \
         FROM fulltext.page_fts f JOIN fulltext.pages p ON p.id = f.rowid \
         WHERE f.page_fts MATCH ",
    )
    .push_bind(query.0.clone());
    let (canton, body) = (text(&s.canton), text(&s.body));
    let (from, to) = (text(&s.from), text(&s.to));
    let on_document = s.commune.is_some()
        || s.year.is_some()
        || [canton, body, from, to].iter().any(Option::is_some);
    if on_document {
        qb.push(" AND p.sha256 IN (SELECT d.sha256 FROM documents d WHERE 1");
        if let Some(commune) = s.commune {
            qb.push(" AND d.sha256 IN (SELECT sha256 FROM document_communes WHERE bfs_id = ")
                .push_bind(commune)
                .push(")");
        }
        if let Some(canton) = canton {
            qb.push(
                " AND d.sha256 IN (SELECT dc.sha256 FROM document_communes dc \
                 JOIN communes c ON c.bfs_id = dc.bfs_id WHERE c.canton = ",
            )
            .push_bind(canton.to_ascii_uppercase())
            .push(")");
        }
        if let Some(year) = s.year {
            qb.push(" AND d.year = ").push_bind(year);
        }
        if let Some(body) = body {
            qb.push(" AND d.body_kind = ").push_bind(body.to_string());
        }
        if let Some(from) = from {
            qb.push(" AND coalesce(d.date, d.listing_date) >= ")
                .push_bind(from.to_string());
        }
        if let Some(to) = to {
            qb.push(" AND coalesce(d.date, d.listing_date) <= ")
                .push_bind(to.to_string());
        }
        qb.push(")");
    }
    // the page lies inside a section of the type or family; the first test is cheap, the second
    // looks at the pages
    for (column, value) in [("type", text(&s.section)), ("family", text(&s.family))] {
        if let Some(value) = value {
            qb.push(format!(
                " AND p.sha256 IN (SELECT sha256 FROM sections WHERE {column} = "
            ))
            .push_bind(value.to_string())
            .push(format!(
                ") AND EXISTS (SELECT 1 FROM sections s WHERE s.sha256 = p.sha256 \
                 AND p.page BETWEEN s.first_page AND s.last_page AND s.{column} = "
            ))
            .push_bind(value.to_string())
            .push(")");
        }
    }
    // `+` keeps FTS5 from ranking every match: SQLite ranks only the pages the filters keep
    qb.push(" ORDER BY +f.rank LIMIT ")
        .push_bind(CAP)
        .push(
            "), doc AS MATERIALIZED (SELECT sha256, min(score) AS score, count(*) AS pages \
             FROM hit GROUP BY sha256), \
             item AS MATERIALIZED (SELECT sha256, score, pages FROM doc \
             ORDER BY score, sha256 LIMIT ",
        )
        .push_bind(s.limit)
        .push(" OFFSET ")
        .push_bind(s.offset)
        .push(") ");
}

/// Everything but the snippets in one statement, so that the index is searched once. The joins
/// start from the matches (CROSS JOIN fixes the order): SQLite would otherwise scan the serving
/// tables.
const SUMMARY: &str = "\
SELECT 'hits' AS kind, NULL AS number, NULL AS text, NULL AS name, count(*) AS n, NULL AS score \
FROM hit \
UNION ALL SELECT 'total', NULL, NULL, NULL, count(*), NULL FROM doc \
UNION ALL SELECT 'year', d.year, NULL, NULL, count(*), NULL \
FROM doc CROSS JOIN documents d ON d.sha256 = doc.sha256 GROUP BY d.year \
UNION ALL SELECT 'section', NULL, s.type, NULL, count(DISTINCT h.sha256), NULL \
FROM hit h CROSS JOIN sections s ON s.sha256 = h.sha256 \
AND h.page BETWEEN s.first_page AND s.last_page GROUP BY s.type \
UNION ALL SELECT 'canton', NULL, c.canton, NULL, count(DISTINCT doc.sha256), NULL \
FROM doc CROSS JOIN document_communes dc ON dc.sha256 = doc.sha256 \
CROSS JOIN communes c ON c.bfs_id = dc.bfs_id GROUP BY c.canton \
UNION ALL SELECT * FROM (SELECT 'commune', c.bfs_id, c.canton, c.name, count(*) AS n, NULL \
FROM doc CROSS JOIN document_communes dc ON dc.sha256 = doc.sha256 \
CROSS JOIN communes c ON c.bfs_id = dc.bfs_id GROUP BY c.bfs_id \
ORDER BY n DESC, c.name, c.bfs_id LIMIT 20) \
UNION ALL SELECT 'item', NULL, sha256, NULL, pages, score FROM item \
UNION ALL SELECT 'page', page, sha256, NULL, id, score FROM (SELECT h.*, row_number() OVER \
(PARTITION BY h.sha256 ORDER BY h.score, h.page) AS position FROM hit h \
WHERE h.sha256 IN (SELECT sha256 FROM item)) WHERE position <= 3";

/// A matching page before its snippet: its number, its id in the index and its score.
struct Best {
    page: i64,
    id: i64,
    score: f64,
}

/// `GET /api/pages`: one page of the documents whose pages match, best first, with their best
/// three pages and the facets. The parameters are checked (`TextSearch::check`).
pub async fn search(pool: &SqlitePool, s: &TextSearch, query: &Query) -> sqlx::Result<TextPage> {
    let mut qb = QueryBuilder::new("");
    push_hits(&mut qb, s, query);
    qb.push(SUMMARY);
    let rows: Vec<Summary> = qb.build_query_as().fetch_all(pool).await?;

    let (mut hits, mut total) = (0, 0);
    let mut facets = TextFacets {
        years: Vec::new(),
        sections: Vec::new(),
        cantons: Vec::new(),
        communes: Vec::new(),
    };
    let mut items: Vec<(String, i64, f64)> = Vec::new();
    let mut best: HashMap<String, Vec<Best>> = HashMap::new();
    for r in rows {
        match r.kind.as_str() {
            "hits" => hits = r.n,
            "total" => total = r.n,
            "year" => facets.years.push(Count {
                value: r.number,
                count: r.n,
            }),
            "section" => facets.sections.push(Count {
                value: r.text,
                count: r.n,
            }),
            "canton" => facets.cantons.push(Count {
                value: r.text,
                count: r.n,
            }),
            "commune" => facets.communes.push(CommuneCount {
                bfs_id: r.number.unwrap_or_default(),
                name: r.name.unwrap_or_default(),
                canton: r.text.unwrap_or_default(),
                count: r.n,
            }),
            "item" => items.push((r.text.unwrap_or_default(), r.n, r.score.unwrap_or(0.0))),
            _ => best
                .entry(r.text.unwrap_or_default())
                .or_default()
                .push(Best {
                    page: r.number.unwrap_or_default(),
                    id: r.n,
                    score: r.score.unwrap_or(0.0),
                }),
        }
    }
    // the order of a compound select's rows is not guaranteed: sort here
    facets
        .years
        .sort_by_key(|c| (c.value.is_none(), std::cmp::Reverse(c.value)));
    facets.sections.sort_by(|a, b| a.value.cmp(&b.value));
    facets.cantons.sort_by(|a, b| a.value.cmp(&b.value));
    facets
        .communes
        .sort_by(|a, b| (b.count, &a.name, a.bfs_id).cmp(&(a.count, &b.name, b.bfs_id)));
    // bm25 scores are negative: the lowest is the best
    items.sort_by(|a, b| a.2.total_cmp(&b.2).then_with(|| a.0.cmp(&b.0)));
    for pages in best.values_mut() {
        pages.sort_by(|a, b| a.score.total_cmp(&b.score).then(a.page.cmp(&b.page)));
    }

    let ids: Vec<i64> = best.values().flatten().map(|b| b.id).collect();
    let mut snippets = snippets(pool, query, &ids).await?;
    let shas: Vec<String> = items.iter().map(|i| i.0.clone()).collect();
    let mut documents: HashMap<String, Document> = documents::by_sha256(pool, &shas)
        .await?
        .into_iter()
        .map(|d| (d.sha256.clone(), d))
        .collect();
    let items = items
        .into_iter()
        // a document the index has and the serving database has not is left out
        .filter_map(|(sha256, matching_pages, _)| {
            let document = documents.remove(&sha256)?;
            let pages = best
                .remove(&sha256)
                .unwrap_or_default()
                .into_iter()
                .map(|b| {
                    let (snippet, highlights) = snippets.remove(&b.id).unwrap_or_default();
                    PageHit {
                        page: b.page,
                        section_types: section_types(&document.sections, b.page),
                        snippet,
                        highlights,
                        original_url: page_url(&sha256, b.page),
                    }
                })
                .collect();
            Some(TextDocument {
                document,
                matching_pages,
                pages,
            })
        })
        .collect();
    Ok(TextPage {
        total,
        capped: hits >= CAP,
        offset: s.offset,
        limit: s.limit,
        facets,
        items,
    })
}

/// The types of the sections that hold the page, each once, in the classifier's order.
fn section_types(sections: &[Section], page: i64) -> Vec<String> {
    let mut types: Vec<String> = Vec::new();
    for s in sections {
        if (s.first_page..=s.last_page).contains(&page) && !types.contains(&s.section_type) {
            types.push(s.section_type.clone());
        }
    }
    types
}

type Snippet = (String, Vec<[u32; 2]>);

/// The snippet of each page id, with its highlights. FTS5 reads each matching page in turn and
/// writes snippets for the ids asked for; `+` keeps it from looking each id up on its own, which
/// for a prefix costs a search of the whole vocabulary per page.
async fn snippets(
    pool: &SqlitePool,
    query: &Query,
    ids: &[i64],
) -> sqlx::Result<HashMap<i64, Snippet>> {
    if ids.is_empty() {
        return Ok(HashMap::new());
    }
    let mut qb = QueryBuilder::new("SELECT rowid, snippet(page_fts, 0, ");
    qb.push_bind(OPEN)
        .push(", ")
        .push_bind(CLOSE)
        .push(", '…', ")
        .push_bind(SNIPPET_WORDS)
        .push(") FROM fulltext.page_fts WHERE page_fts MATCH ")
        .push_bind(query.0.clone())
        .push(" AND +rowid IN (");
    let mut list = qb.separated(", ");
    for id in ids {
        list.push_bind(*id);
    }
    qb.push(") LIMIT ").push_bind(ids.len() as i64);
    let rows: Vec<(i64, String)> = qb.build_query_as().fetch_all(pool).await?;
    Ok(rows
        .into_iter()
        .map(|(id, marked)| (id, snippet(&marked)))
        .collect())
}

/// A snippet as plain text and the character ranges of its matches. Runs of white space and
/// control characters become one space; a snippet over `SNIPPET_CHARS` characters is cut around
/// its first match.
fn snippet(marked: &str) -> Snippet {
    let mut chars: Vec<char> = Vec::new();
    let mut highlights: Vec<[usize; 2]> = Vec::new();
    let (mut start, mut space) = (None, false);
    let mut rest = marked;
    while let Some(c) = rest.chars().next() {
        if let Some(after) = rest.strip_prefix(OPEN) {
            if space {
                chars.push(' ');
                space = false;
            }
            start = Some(chars.len());
            rest = after;
            continue;
        }
        if let Some(after) = rest.strip_prefix(CLOSE) {
            if let Some(s) = start.take().filter(|s| *s < chars.len()) {
                highlights.push([s, chars.len()]);
            }
            rest = after;
            continue;
        }
        rest = &rest[c.len_utf8()..];
        if c.is_whitespace() || c.is_control() {
            space = !chars.is_empty();
        } else {
            if space {
                chars.push(' ');
                space = false;
            }
            chars.push(c);
        }
    }
    if chars.len() > SNIPPET_CHARS {
        // keep the first match, with some text before it
        let first = highlights.first().map_or(0, |h| h[0]);
        let from = first.saturating_sub(SNIPPET_CHARS / 4);
        let to = (from + SNIPPET_CHARS).min(chars.len());
        let lead = usize::from(from > 0);
        let mut cut: Vec<char> = Vec::with_capacity(to - from + 2);
        if from > 0 {
            cut.push('…');
        }
        cut.extend(&chars[from..to]);
        if to < chars.len() {
            cut.push('…');
        }
        highlights = highlights
            .into_iter()
            .filter(|h| h[0] >= from && h[1] <= to)
            .map(|h| [h[0] - from + lead, h[1] - from + lead])
            .collect();
        chars = cut;
    }
    let highlights = highlights
        .into_iter()
        .map(|[a, b]| [a as u32, b as u32])
        .collect();
    (chars.into_iter().collect(), highlights)
}

/// The parameters of `GET /api/documents/{sha256}/pages` and of the MCP tool `read_pages`.
#[derive(Deserialize, JsonSchema)]
#[schemars(crate = "rmcp::schemars")]
pub struct PageRange {
    /// The first page to read; 1, the default, is the first page of the file.
    #[serde(default)]
    pub from: Option<i64>,
    /// The last page to read. From `from` to `to` are at most 10 pages. Default: `from` + 9.
    #[serde(default)]
    pub to: Option<i64>,
}

impl PageRange {
    /// The first and the last page, or why the range is refused.
    pub fn check(&self) -> Result<(i64, i64), String> {
        let from = self.from.unwrap_or(1);
        if from < 1 {
            return Err("from must be 1 or more".into());
        }
        let to = self.to.unwrap_or(from + MAX_PAGES - 1);
        if to < from {
            return Err("to must not be before from".into());
        }
        if to - from >= MAX_PAGES {
            return Err(format!("at most {MAX_PAGES} pages at a time"));
        }
        Ok((from, to))
    }
}

const LEFT_OUT: &str = "Not searched: the search leaves out bulletins and the documents of \
private bodies.";
const OUTSIDE: &str = "Not searched: the page lies in no section of a type the search covers.";
const NO_TEXT: &str = "No text yet: the page has no usable text layer, and OCR has not \
reached it.";

/// `GET /api/documents/{sha256}/pages`: the pages `from` to `to` (not past the document's last
/// page), with their text when the index has it. None for an unknown document.
pub async fn read(
    pool: &SqlitePool,
    sha256: &str,
    from: i64,
    to: i64,
) -> sqlx::Result<Option<DocumentPages>> {
    // the same documents are left out as in fulltext.py
    let document: Option<(Option<i64>, bool)> = sqlx::query_as(
        "SELECT page_count, kind IS 'bulletin' OR body_kind IS 'private' FROM documents \
         WHERE sha256 = ?",
    )
    .bind(sha256)
    .fetch_optional(pool)
    .await?;
    let Some((page_count, left_out)) = document else {
        return Ok(None);
    };
    let to = page_count.map_or(to, |count| to.min(count));
    let sections: Vec<Section> = sqlx::query_as(
        "SELECT sha256, type AS section_type, family, first_page, last_page, partly_unseen \
         FROM sections WHERE sha256 = ? ORDER BY position",
    )
    .bind(sha256)
    .fetch_all(pool)
    .await?;
    let mut texts: HashMap<i64, (String, String)> = sqlx::query_as(
        "SELECT p.page, p.source, f.text FROM fulltext.pages p \
         CROSS JOIN fulltext.page_fts f ON f.rowid = p.id \
         WHERE p.sha256 = ? AND p.page BETWEEN ? AND ?",
    )
    .bind(sha256)
    .bind(from)
    .bind(to)
    .fetch_all(pool)
    .await?
    .into_iter()
    .map(|(page, source, text): (i64, String, String)| (page, (source, text)))
    .collect();
    let searched = searched_types(pool).await?;
    let pages = (from..=to)
        .map(|page| {
            let types = section_types(&sections, page);
            let (source, text, reason) = match texts.remove(&page) {
                Some((source, text)) => (Some(source), Some(text), None),
                None if left_out => (None, None, Some(LEFT_OUT)),
                None if !types.iter().any(|t| searched.contains(t)) => (None, None, Some(OUTSIDE)),
                None => (None, None, Some(NO_TEXT)),
            };
            PageText {
                page,
                section_types: types,
                source,
                text,
                reason: reason.map(str::to_string),
                original_url: page_url(sha256, page),
            }
        })
        .collect();
    Ok(Some(DocumentPages {
        sha256: sha256.to_string(),
        page_count,
        pages,
    }))
}

/// The section types the index covers: the keys of its count per section type.
async fn searched_types(pool: &SqlitePool) -> sqlx::Result<HashSet<String>> {
    let counts: Option<String> =
        sqlx::query_scalar("SELECT value FROM fulltext.build WHERE key = 'section_types'")
            .fetch_optional(pool)
            .await?;
    let counts: serde_json::Map<String, serde_json::Value> = counts
        .and_then(|c| serde_json::from_str(&c).ok())
        .unwrap_or_default();
    Ok(counts.into_iter().map(|(kind, _)| kind).collect())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn parse(q: &str) -> Result<String, String> {
        Query::parse(q).map(|q| q.0)
    }

    #[test]
    fn every_word_and_phrase_is_quoted() {
        assert_eq!(parse("Steuerfuss").unwrap(), r#""Steuerfuss""#);
        assert_eq!(
            parse("  preventivo   2025 ").unwrap(),
            r#""preventivo" "2025""#
        );
        assert_eq!(
            parse(r#""Investitionskredit für""#).unwrap(),
            r#""Investitionskredit für""#
        );
        assert_eq!(
            parse("crédit d'engagement").unwrap(),
            r#""crédit" "d'engagement""#
        );
        assert_eq!(parse("Tempo* 30").unwrap(), r#""Tempo"* "30""#);
        assert_eq!(parse(r#""tempo dreis"*"#).unwrap(), r#""tempo dreis"*"#);
        // FTS5 syntax is text
        assert_eq!(
            parse("a OR b NOT text:c (d) NEAR(e f)").unwrap(),
            r#""a" "OR" "b" "NOT" "text:c" "(d)" "NEAR(e" "f)""#
        );
        assert_eq!(parse(r#"x"y"#).unwrap(), r#""x" "y""#); // a quote starts a phrase
        assert_eq!(
            parse(r#""unclosed phrase"#).unwrap(),
            r#""unclosed phrase""#
        );
        assert_eq!(parse("Gemeinde - § 12").unwrap(), r#""Gemeinde" "12""#);
        assert_eq!(parse("abc**").unwrap(), r#""abc"*"#);
    }

    #[test]
    fn queries_without_words_or_with_short_prefixes_are_refused() {
        for q in [
            "",
            "   ",
            "\"\"",
            "*",
            "- §",
            "\"",
            "ge*",
            "d'e*",
            "\"tempo 3\"*",
        ] {
            assert!(Query::parse(q).is_err(), "{q:?}");
        }
        assert!(Query::parse(&"wort ".repeat(MAX_TERMS)).is_ok());
        assert!(Query::parse(&"wort ".repeat(MAX_TERMS + 1)).is_err());
        assert!(Query::parse(&"x".repeat(MAX_QUERY_CHARS + 1)).is_err());
    }

    #[test]
    fn dates_and_ranges_are_checked() {
        assert!(is_date("2024-01-31"));
        for bad in [
            "2024-1-31",
            "2024/01/31",
            "24-01-31",
            "2024-01-311",
            "abcd-ef-gh",
        ] {
            assert!(!is_date(bad), "{bad}");
        }
        let range = |from, to| PageRange { from, to }.check();
        assert_eq!(range(None, None), Ok((1, 10)));
        assert_eq!(range(Some(5), None), Ok((5, 14)));
        assert_eq!(range(Some(5), Some(5)), Ok((5, 5)));
        assert!(range(Some(0), None).is_err());
        assert!(range(Some(5), Some(4)).is_err());
        assert!(range(Some(1), Some(11)).is_err());
    }

    #[test]
    fn snippets_are_plain_text_with_ranges() {
        let marked =
            format!("…der \n\n {OPEN}Steuerfuss{CLOSE} von\t119 %, {OPEN}Tempo{CLOSE} \u{1}30");
        let (text, highlights) = snippet(&marked);
        assert_eq!(text, "…der Steuerfuss von 119 %, Tempo 30");
        assert_eq!(highlights, [[5, 15], [27, 32]]);
        let chars: Vec<char> = text.chars().collect();
        assert_eq!(chars[5..15].iter().collect::<String>(), "Steuerfuss");
        // a long snippet is cut around its first match
        let long = format!(
            "{} {OPEN}Treffer{CLOSE} {}",
            "a".repeat(600),
            "b".repeat(600)
        );
        let (text, highlights) = snippet(&long);
        let chars: Vec<char> = text.chars().collect();
        assert_eq!(chars.len(), SNIPPET_CHARS + 2);
        let [a, b] = highlights[0];
        assert_eq!(
            chars[a as usize..b as usize].iter().collect::<String>(),
            "Treffer"
        );
        assert!(text.starts_with('…') && text.ends_with('…'));
    }
}
