//! Full-text search over page text: the search with its facets, and the text of a range of pages.
//!
//! The index is `fulltext.db` (`src/opencommune/fulltext.py`), attached to every connection as the
//! schema `fulltext`: `pages (id, sha256, page, source, run)` and `page_fts`, an FTS5 table whose
//! rowid is `pages.id`. Section types, communes, years, bodies, languages and dates come from the
//! serving database, joined on sha256 and page.

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
/// The largest distance in `NEAR(…, N)`, in words; a page has a few hundred.
const MAX_NEAR: u32 = 1000;
/// The matching pages shown per document, by default and at most.
pub const DEFAULT_PAGES_PER_DOCUMENT: i64 = 3;
pub const MAX_PAGES_PER_DOCUMENT: i64 = 20;
/// The communes the commune facet lists, by default and at most (more than Switzerland has).
pub const DEFAULT_COMMUNE_FACETS: i64 = 20;
pub const MAX_COMMUNE_FACETS: i64 = 3000;
/// A snippet's length in characters: one passage of this length, or two of half of it. A passage
/// grows by up to `WORD_EDGE` characters at each end so as not to cut a word.
const SNIPPET_CHARS: usize = 360;
const WORD_EDGE: usize = 10;
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
    /// it (at least 3 letters before the *). OR between words, phrases or groups: either may
    /// occur; it binds less tightly than the words around it, and (parentheses) group.
    /// NEAR(a b, 10): the words at most 10 words apart (10 is the default). Case and accents do
    /// not matter. Refused: a * other than at the end of a word, -word and NOT.
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
    /// Languages, comma-separated (de, fr, it, rm): documents in one of them.
    #[serde(default)]
    pub language: Option<String>,
    /// Section types, comma-separated: only pages inside a section of one of them match.
    #[serde(default)]
    pub section: Option<String>,
    /// Section families, comma-separated: only pages inside a section of one of them match.
    #[serde(default)]
    pub family: Option<String>,
    /// Section types, comma-separated: pages inside a section of one of them do not match.
    #[serde(default)]
    pub exclude_section: Option<String>,
    /// Section families, comma-separated: pages inside a section of one of them do not match.
    #[serde(default)]
    pub exclude_family: Option<String>,
    /// The kind of body behind the document.
    #[serde(default)]
    pub body: Option<String>,
    /// A document's sha256: search inside this document only.
    #[serde(default)]
    pub document: Option<String>,
    /// The order of the documents: relevance (the default: best match first), newest or oldest
    /// (by the document's date, else the listing date; undated documents last).
    #[serde(default)]
    pub sort: Option<String>,
    /// Documents to skip.
    #[serde(default)]
    pub offset: i64,
    /// Documents to return, 0 to 50.
    #[serde(default = "default_limit")]
    pub limit: i64,
    /// The matching pages to show per document, best first: 1 to 20, default 3.
    #[serde(default = "default_pages_per_document")]
    pub pages_per_document: i64,
    /// The communes the commune facet lists, most documents first: 0 to 3000, default 20; 3000
    /// lists them all.
    #[serde(default = "default_commune_facets")]
    pub commune_facets: i64,
}

fn default_limit() -> i64 {
    DEFAULT_LIMIT
}

fn default_pages_per_document() -> i64 {
    DEFAULT_PAGES_PER_DOCUMENT
}

fn default_commune_facets() -> i64 {
    DEFAULT_COMMUNE_FACETS
}

/// The order of the documents of a search.
#[derive(Clone, Copy, PartialEq)]
enum Sort {
    Relevance,
    Newest,
    Oldest,
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
        if !(1..=MAX_PAGES_PER_DOCUMENT).contains(&self.pages_per_document) {
            return Err(format!(
                "pages_per_document must be between 1 and {MAX_PAGES_PER_DOCUMENT}"
            ));
        }
        if !(0..=MAX_COMMUNE_FACETS).contains(&self.commune_facets) {
            return Err(format!(
                "commune_facets must be between 0 and {MAX_COMMUNE_FACETS}"
            ));
        }
        for (name, value) in [("from", &self.from), ("to", &self.to)] {
            if text(value).is_some_and(|v| !is_date(v)) {
                return Err(format!("{name} must be a date: YYYY-MM-DD"));
            }
        }
        self.sort()?;
        Query::parse(&self.q)
    }

    fn sort(&self) -> Result<Sort, String> {
        match text(&self.sort) {
            None | Some("relevance") => Ok(Sort::Relevance),
            Some("newest") => Ok(Sort::Newest),
            Some("oldest") => Ok(Sort::Oldest),
            Some(_) => Err("sort must be relevance, newest or oldest".into()),
        }
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

/// The values of a comma-separated parameter, blanks left out.
fn values(value: &Option<String>) -> Vec<&str> {
    value
        .as_deref()
        .unwrap_or("")
        .split(',')
        .map(str::trim)
        .filter(|v| !v.is_empty())
        .collect()
}

const STAR: &str = "a * can only end a word or a phrase: Kunstrasen* finds the words that begin \
with Kunstrasen; words that end in a word (*rasen) cannot be searched";
const MINUS: &str = "there is no exclusion with -: leave the - out to search the word, or use \
exclude_section to leave out pages";
const NOT: &str = "NOT is not supported: leave out pages with exclude_section or exclude_family; \
to search the word, put it in quotes: \"NOT\"";
const OPERAND: &str = "OR and AND need a word, a phrase or a group on each side; to search the \
word, put it in quotes: \"OR\"";

/// A search query as an FTS5 expression. Every word and phrase of the input is one quoted FTS5
/// string and the server writes the operators, so nothing a user types reaches FTS5 as syntax.
pub struct Query(String);

/// A piece of the query as typed.
#[derive(Clone, Debug, PartialEq)]
enum Token {
    /// A word or a phrase as an FTS5 string, with `*` when it is a prefix.
    Term(String),
    Or,
    And,
    Open,
    Close,
    /// `NEAR(…)`: its words and phrases, and the distance.
    Near(Vec<String>, Option<u32>),
}

/// The query as a tree: AND binds more tightly than OR.
enum Node {
    Term(String),
    Near(Vec<String>, Option<u32>),
    And(Vec<Node>),
    Or(Vec<Node>),
}

impl Query {
    /// Reads the search box's syntax: words, "phrases", prefixes (`word*`, `"a phrase"*`), OR,
    /// AND, (groups) and `NEAR(…, N)`. OR, AND and NEAR are operators in capitals only. A word
    /// without a letter or a digit is left out. An unclosed quote or parenthesis runs to the end.
    pub fn parse(input: &str) -> Result<Query, String> {
        if input.chars().count() > MAX_QUERY_CHARS {
            return Err(format!("q is longer than {MAX_QUERY_CHARS} characters"));
        }
        let tokens = tokens(input)?;
        let terms: usize = tokens
            .iter()
            .map(|t| match t {
                Token::Term(_) => 1,
                Token::Near(terms, _) => terms.len(),
                _ => 0,
            })
            .sum();
        if terms > MAX_TERMS {
            return Err(format!("q has more than {MAX_TERMS} words and phrases"));
        }
        let mut parser = Parser { tokens, at: 0 };
        let node = parser.any()?;
        if parser.at < parser.tokens.len() {
            return Err("a ) without its (".into());
        }
        Ok(Query(fts(&node, false)))
    }
}

/// The input as tokens.
fn tokens(input: &str) -> Result<Vec<Token>, String> {
    let mut out = Vec::new();
    let mut chars = input.chars().peekable();
    while let Some(&first) = chars.peek() {
        match first {
            c if c.is_whitespace() => {
                chars.next();
            }
            '(' => {
                chars.next();
                out.push(Token::Open);
            }
            ')' => {
                chars.next();
                out.push(Token::Close);
            }
            '"' => {
                chars.next();
                let phrase: String = chars.by_ref().take_while(|c| *c != '"').collect();
                let mut prefix = false;
                while chars.next_if_eq(&'*').is_some() {
                    prefix = true;
                }
                out.extend(term(&phrase, prefix)?.map(Token::Term));
            }
            _ => {
                let mut word = String::new();
                while let Some(c) =
                    chars.next_if(|c| !c.is_whitespace() && !matches!(c, '"' | '(' | ')'))
                {
                    word.push(c);
                }
                match word.as_str() {
                    "OR" => out.push(Token::Or),
                    "AND" => out.push(Token::And),
                    "NOT" => return Err(NOT.into()),
                    "NEAR" if chars.clone().find(|c| !c.is_whitespace()) == Some('(') => {
                        chars.find(|c| *c == '(');
                        out.push(near(&mut chars)?);
                    }
                    _ => {
                        let mut minus = word.chars();
                        if minus.next() == Some('-')
                            && minus.next().is_some_and(char::is_alphanumeric)
                        {
                            return Err(MINUS.into());
                        }
                        let stem = word.trim_end_matches('*');
                        let prefix = stem.len() < word.len();
                        out.extend(term(stem, prefix)?.map(Token::Term));
                    }
                }
            }
        }
    }
    Ok(out)
}

/// A word or a phrase as an FTS5 string; None when it has no letter or digit.
fn term(text: &str, prefix: bool) -> Result<Option<String>, String> {
    if text.contains('*') {
        return Err(STAR.into());
    }
    let Some(last) = text
        .split(|c: char| !c.is_alphanumeric())
        .rfind(|w| !w.is_empty())
    else {
        return Ok(None);
    };
    if prefix && last.chars().count() < MIN_PREFIX {
        return Err(format!(
            "a word before * needs at least {MIN_PREFIX} letters or digits"
        ));
    }
    let star = if prefix { "*" } else { "" };
    Ok(Some(format!("\"{}\"{star}", text.replace('"', "\"\""))))
}

/// The inside of `NEAR(` up to its `)`: words and phrases, then `, N` if given.
fn near(chars: &mut std::iter::Peekable<std::str::Chars>) -> Result<Token, String> {
    let mut inside = String::new();
    let mut quoted = false;
    for c in chars.by_ref() {
        if c == ')' && !quoted {
            break;
        }
        quoted ^= c == '"';
        inside.push(c);
    }
    let mut distance = None;
    if let Some((words, n)) = inside.rsplit_once(',') {
        let n = n.trim();
        if !n.is_empty() && n.chars().all(|c| c.is_ascii_digit()) {
            match n.parse::<u32>() {
                Ok(n) if n <= MAX_NEAR => distance = Some(n),
                _ => {
                    return Err(format!(
                        "the distance in NEAR(…, N) is 0 to {MAX_NEAR} words"
                    ));
                }
            }
            inside = words.to_string();
        }
    }
    let mut terms = Vec::new();
    for token in tokens(&inside)? {
        match token {
            Token::Term(t) => terms.push(t),
            _ => return Err("NEAR(…) holds words and phrases only".into()),
        }
    }
    if terms.len() < 2 {
        return Err("NEAR(…) needs at least two words or phrases".into());
    }
    Ok(Token::Near(terms, distance))
}

struct Parser {
    tokens: Vec<Token>,
    at: usize,
}

impl Parser {
    fn peek(&self) -> Option<&Token> {
        self.tokens.get(self.at)
    }

    /// Alternatives: `all (OR all)*`.
    fn any(&mut self) -> Result<Node, String> {
        let mut parts = vec![self.all()?];
        while self.peek() == Some(&Token::Or) {
            self.at += 1;
            parts.push(self.all()?);
        }
        Ok(if parts.len() == 1 {
            parts.remove(0)
        } else {
            Node::Or(parts)
        })
    }

    /// What must all occur: `unit ([AND] unit)*`.
    fn all(&mut self) -> Result<Node, String> {
        let mut parts = Vec::new();
        loop {
            match self.peek() {
                Some(Token::Term(_) | Token::Near(..) | Token::Open) => parts.push(self.unit()?),
                Some(Token::And) if !parts.is_empty() => {
                    self.at += 1;
                    if !matches!(
                        self.peek(),
                        Some(Token::Term(_) | Token::Near(..) | Token::Open)
                    ) {
                        return Err(OPERAND.into());
                    }
                }
                _ => break,
            }
        }
        if parts.is_empty() {
            return Err(match self.peek() {
                None if self.at == 0 => "q has no word to search for".into(),
                Some(Token::Close) if self.at > 0 && self.tokens[self.at - 1] == Token::Open => {
                    "a group ( ) has no word".into()
                }
                Some(Token::Close) if self.at == 0 => "a ) without its (".into(),
                _ => OPERAND.into(),
            });
        }
        Ok(if parts.len() == 1 {
            parts.remove(0)
        } else {
            Node::And(parts)
        })
    }

    fn unit(&mut self) -> Result<Node, String> {
        let token = self.tokens[self.at].clone();
        self.at += 1;
        Ok(match token {
            Token::Term(t) => Node::Term(t),
            Token::Near(terms, distance) => Node::Near(terms, distance),
            _ => {
                let inside = self.any()?;
                // an unclosed group runs to the end
                if self.peek() == Some(&Token::Close) {
                    self.at += 1;
                }
                inside
            }
        })
    }
}

/// The tree as an FTS5 expression, a group in parentheses. FTS5 needs AND before a parenthesis.
fn fts(node: &Node, nested: bool) -> String {
    let join = |parts: &[Node], operator: &str| {
        let inner: Vec<String> = parts.iter().map(|p| fts(p, true)).collect();
        let inner = inner.join(operator);
        if nested { format!("({inner})") } else { inner }
    };
    match node {
        Node::Term(t) => t.clone(),
        Node::Near(terms, distance) => match distance {
            Some(n) => format!("NEAR({}, {n})", terms.join(" ")),
            None => format!("NEAR({})", terms.join(" ")),
        },
        Node::And(parts) => join(parts, " AND "),
        Node::Or(parts) => join(parts, " OR "),
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

/// ` IN (?, ?, …)` with the values bound.
fn push_in(qb: &mut QueryBuilder<Sqlite>, values: &[&str]) {
    qb.push(" IN (");
    let mut list = qb.separated(", ");
    for value in values {
        list.push_bind(value.to_string());
    }
    qb.push(")");
}

/// The query up to the matching pages: `hit` holds the first `CAP` pages, in the order asked for,
/// that match and pass the filters; `doc` their documents with the best score, the number of pages
/// and the date; `item` the documents of the requested page of results with their position.
fn push_hits(qb: &mut QueryBuilder<Sqlite>, s: &TextSearch, query: &Query, sort: Sort) {
    // the date is looked up for every matching page only when the documents are sorted by it
    let day = if sort == Sort::Relevance {
        "NULL"
    } else {
        "(SELECT coalesce(d.date, d.listing_date) FROM documents d WHERE d.sha256 = p.sha256)"
    };
    qb.push(format!(
        "WITH hit AS MATERIALIZED (SELECT p.id, p.sha256, p.page, f.rank AS score, {day} AS day \
         FROM fulltext.page_fts f JOIN fulltext.pages p ON p.id = f.rowid \
         WHERE f.page_fts MATCH "
    ))
    .push_bind(query.0.clone());
    if let Some(document) = text(&s.document) {
        // a document's pages have neighbouring ids (fulltext.py writes them in order), so the
        // range lets FTS5 skip the other documents' matches; the sha256 test decides
        qb.push(" AND f.rowid BETWEEN (SELECT min(id) FROM fulltext.pages WHERE sha256 = ")
            .push_bind(document.to_string())
            .push(") AND (SELECT max(id) FROM fulltext.pages WHERE sha256 = ")
            .push_bind(document.to_string())
            .push(") AND p.sha256 = ")
            .push_bind(document.to_string());
    }
    let (canton, body) = (text(&s.canton), text(&s.body));
    let (from, to) = (text(&s.from), text(&s.to));
    let languages = values(&s.language);
    let on_document = s.commune.is_some()
        || s.year.is_some()
        || !languages.is_empty()
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
        if !languages.is_empty() {
            // `languages` is a comma-separated list such as "fr,de"
            qb.push(" AND (0");
            for language in languages {
                qb.push(" OR instr(',' || coalesce(d.languages, '') || ',', ")
                    .push_bind(format!(",{},", language.to_lowercase()))
                    .push(") > 0");
            }
            qb.push(")");
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
    // the page lies inside a section of one of the types or families; the first test is cheap,
    // the second looks at the pages
    for (column, kept) in [("type", &s.section), ("family", &s.family)] {
        let kept = values(kept);
        if !kept.is_empty() {
            qb.push(format!(
                " AND p.sha256 IN (SELECT sha256 FROM sections WHERE {column}"
            ));
            push_in(qb, &kept);
            qb.push(format!(
                ") AND EXISTS (SELECT 1 FROM sections s WHERE s.sha256 = p.sha256 \
                 AND p.page BETWEEN s.first_page AND s.last_page AND s.{column}"
            ));
            push_in(qb, &kept);
            qb.push(")");
        }
    }
    // ... and in no section of the types or families left out
    for (column, left_out) in [("type", &s.exclude_section), ("family", &s.exclude_family)] {
        let left_out = values(left_out);
        if !left_out.is_empty() {
            qb.push(format!(
                " AND NOT EXISTS (SELECT 1 FROM sections s WHERE s.sha256 = p.sha256 \
                 AND p.page BETWEEN s.first_page AND s.last_page AND s.{column}"
            ));
            push_in(qb, &left_out);
            qb.push(")");
        }
    }
    // `+` keeps FTS5 from ranking every match: SQLite ranks only the pages the filters keep
    let (pages, documents) = match sort {
        Sort::Relevance => ("+f.rank", "score, sha256"),
        Sort::Newest => (
            "day DESC NULLS LAST, +f.rank",
            "day DESC NULLS LAST, score, sha256",
        ),
        Sort::Oldest => ("day NULLS LAST, +f.rank", "day NULLS LAST, score, sha256"),
    };
    qb.push(format!(" ORDER BY {pages} LIMIT "))
        .push_bind(CAP)
        .push(format!(
            "), doc AS MATERIALIZED (SELECT sha256, min(score) AS score, count(*) AS pages, \
             max(day) AS day FROM hit GROUP BY sha256), \
             item AS MATERIALIZED (SELECT sha256, score, pages, \
             row_number() OVER (ORDER BY {documents}) AS position FROM doc \
             ORDER BY position LIMIT "
        ))
        .push_bind(s.limit)
        .push(" OFFSET ")
        .push_bind(s.offset)
        .push(") ");
}

/// Everything but the snippets in one statement, so that the index is searched once. The joins
/// start from the matches (CROSS JOIN fixes the order): SQLite would otherwise scan the serving
/// tables. The number of communes follows, then the rest, then the number of pages to show per
/// document.
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
ORDER BY n DESC, c.name, c.bfs_id LIMIT ";
const SUMMARY_REST: &str = ") \
UNION ALL SELECT 'item', position, sha256, NULL, pages, score FROM item \
UNION ALL SELECT 'page', page, sha256, NULL, id, score FROM (SELECT h.*, row_number() OVER \
(PARTITION BY h.sha256 ORDER BY h.score, h.page) AS position FROM hit h \
WHERE h.sha256 IN (SELECT sha256 FROM item)) WHERE position <= ";

/// A matching page before its snippet: its number, its id in the index and its score.
struct Best {
    page: i64,
    id: i64,
    score: f64,
}

/// `GET /api/pages`: one page of the documents whose pages match, in the order asked for, with
/// their best pages and the facets. The parameters are checked (`TextSearch::check`); links start
/// with `base`, the site's public address.
pub async fn search(
    pool: &SqlitePool,
    s: &TextSearch,
    query: &Query,
    base: &str,
) -> sqlx::Result<TextPage> {
    let mut qb = QueryBuilder::new("");
    push_hits(&mut qb, s, query, s.sort().unwrap_or(Sort::Relevance));
    qb.push(SUMMARY)
        .push_bind(s.commune_facets)
        .push(SUMMARY_REST)
        .push_bind(s.pages_per_document);
    let rows: Vec<Summary> = qb.build_query_as().fetch_all(pool).await?;

    let (mut hits, mut total) = (0, 0);
    let mut facets = TextFacets {
        years: Vec::new(),
        sections: Vec::new(),
        cantons: Vec::new(),
        communes: Vec::new(),
    };
    // a document, its number of matching pages and its position in the result
    let mut items: Vec<(String, i64, i64)> = Vec::new();
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
            "item" => items.push((r.text.unwrap_or_default(), r.n, r.number.unwrap_or(0))),
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
    items.sort_by_key(|i| i.2);
    // bm25 scores are negative: the lowest is the best
    for pages in best.values_mut() {
        pages.sort_by(|a, b| a.score.total_cmp(&b.score).then(a.page.cmp(&b.page)));
    }

    let ids: Vec<i64> = best.values().flatten().map(|b| b.id).collect();
    let mut snippets = snippets(pool, query, &ids).await?;
    let shas: Vec<String> = items.iter().map(|i| i.0.clone()).collect();
    let mut documents: HashMap<String, Document> = documents::by_sha256(pool, &shas, base)
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
                        original_url: page_url(base, &sha256, b.page),
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
/// marks the matches in the whole text of the ids asked for (`highlight()`); `snippet` picks the
/// passages. `+` keeps FTS5 from looking each id up on its own, which for a prefix costs a search
/// of the whole vocabulary per page.
async fn snippets(
    pool: &SqlitePool,
    query: &Query,
    ids: &[i64],
) -> sqlx::Result<HashMap<i64, Snippet>> {
    if ids.is_empty() {
        return Ok(HashMap::new());
    }
    let mut qb = QueryBuilder::new("SELECT rowid, highlight(page_fts, 0, ");
    qb.push_bind(OPEN)
        .push(", ")
        .push_bind(CLOSE)
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

/// A page's snippet, from its text with FTS5's marks around the matches: the whole text when it is
/// short, else the passage of `SNIPPET_CHARS` characters that shows the most different matched
/// words, or two passages of half that length when together they show more. Plain text: runs of
/// white space and control characters become one space; `…` marks a cut.
fn snippet(marked: &str) -> Snippet {
    let (chars, highlights) = unmark(marked);
    if chars.len() <= SNIPPET_CHARS {
        return join(&chars, &highlights, &[(0, chars.len())]);
    }
    // a matched word as a key: its letters and digits in lower case
    let keys: Vec<String> = highlights
        .iter()
        .map(|[a, b]| {
            chars[*a..*b]
                .iter()
                .filter(|c| c.is_alphanumeric())
                .flat_map(|c| c.to_lowercase())
                .collect()
        })
        .collect();
    let different = keys.iter().collect::<HashSet<_>>().len();
    let none = HashSet::new();
    let one = passage(&chars, &highlights, &keys, SNIPPET_CHARS, &none, None);
    let mut passages = vec![(one.0, one.1)];
    if one.2.len() < different {
        let first = passage(&chars, &highlights, &keys, SNIPPET_CHARS / 2, &none, None);
        let around = Some((first.0, first.1));
        let second = passage(
            &chars,
            &highlights,
            &keys,
            SNIPPET_CHARS / 2,
            &first.2,
            around,
        );
        if !second.2.is_empty() && first.2.len() + second.2.len() > one.2.len() {
            passages = vec![(first.0, first.1), (second.0, second.1)];
            passages.sort();
        }
    }
    join(&chars, &highlights, &passages)
}

/// FTS5's marked text as characters, with runs of white space and control characters as one
/// space, and the character ranges of the matches.
fn unmark(marked: &str) -> (Vec<char>, Vec<[usize; 2]>) {
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
    (chars, highlights)
}

/// The passage of about `len` characters around a match that shows the most matched words not in
/// `seen`, then the most matches, then comes first; it does not overlap `avoid`. Its start, its
/// end and the new words it shows.
fn passage<'k>(
    chars: &[char],
    highlights: &[[usize; 2]],
    keys: &'k [String],
    len: usize,
    seen: &HashSet<&'k str>,
    avoid: Option<(usize, usize)>,
) -> (usize, usize, HashSet<&'k str>) {
    let mut best: Option<(usize, usize, HashSet<&'k str>, usize)> = None;
    for h in highlights {
        let start = h[0]
            .saturating_sub(len / 4)
            .min(chars.len().saturating_sub(len));
        let (start, end) = whole_words(chars, start, (start + len).min(chars.len()));
        if avoid.is_some_and(|(a, b)| start < b && a < end) {
            continue;
        }
        let inside: Vec<usize> = (0..highlights.len())
            .filter(|&i| highlights[i][0] >= start && highlights[i][1] <= end)
            .collect();
        let new: HashSet<&'k str> = inside
            .iter()
            .map(|&i| keys[i].as_str())
            .filter(|k| !seen.contains(k))
            .collect();
        if best
            .as_ref()
            .is_none_or(|b| (new.len(), inside.len()) > (b.2.len(), b.3))
        {
            best = Some((start, end, new, inside.len()));
        }
    }
    best.map_or((0, len.min(chars.len()), HashSet::new()), |b| {
        (b.0, b.1, b.2)
    })
}

/// `start` and `end` moved out to the nearest space, by at most `WORD_EDGE` characters each.
fn whole_words(chars: &[char], start: usize, end: usize) -> (usize, usize) {
    let start = (start.saturating_sub(WORD_EDGE)..=start)
        .rev()
        .find(|&i| i == 0 || chars[i - 1] == ' ')
        .unwrap_or(start);
    let end = (end..=(end + WORD_EDGE).min(chars.len()))
        .find(|&i| i == chars.len() || chars[i] == ' ')
        .unwrap_or(end);
    (start, end)
}

/// The passages as one snippet, `…` where text is left out, and the matches inside the passages
/// as character ranges of the snippet.
fn join(chars: &[char], highlights: &[[usize; 2]], passages: &[(usize, usize)]) -> Snippet {
    let mut out: Vec<char> = Vec::new();
    let mut ranges: Vec<[u32; 2]> = Vec::new();
    for (n, &(start, end)) in passages.iter().enumerate() {
        if n > 0 {
            out.extend([' ', '…', ' ']);
        } else if start > 0 {
            out.push('…');
        }
        let offset = out.len();
        out.extend(&chars[start..end]);
        for h in highlights.iter().filter(|h| h[0] >= start && h[1] <= end) {
            ranges.push([
                (h[0] - start + offset) as u32,
                (h[1] - start + offset) as u32,
            ]);
        }
    }
    if passages.last().is_some_and(|&(_, end)| end < chars.len()) {
        out.push('…');
    }
    (out.into_iter().collect(), ranges)
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
/// page), with their text when the index has it. None for an unknown document. Links start with
/// `base`, the site's public address.
pub async fn read(
    pool: &SqlitePool,
    sha256: &str,
    from: i64,
    to: i64,
    base: &str,
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
                original_url: page_url(base, sha256, page),
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
            r#""preventivo" AND "2025""#
        );
        assert_eq!(
            parse(r#""Investitionskredit für""#).unwrap(),
            r#""Investitionskredit für""#
        );
        assert_eq!(
            parse("crédit d'engagement").unwrap(),
            r#""crédit" AND "d'engagement""#
        );
        assert_eq!(parse("Tempo* 30").unwrap(), r#""Tempo"* AND "30""#);
        assert_eq!(parse(r#""tempo dreis"*"#).unwrap(), r#""tempo dreis"*"#);
        // FTS5 syntax is text; or, and, not and near in small letters are words
        assert_eq!(
            parse("a or b not text:c ^d near(e f) {g}").unwrap(),
            r#""a" AND "or" AND "b" AND "not" AND "text:c" AND "^d" AND "near" AND ("e" AND "f") AND "{g}""#
        );
        assert_eq!(parse(r#""OR" "NOT""#).unwrap(), r#""OR" AND "NOT""#);
        assert_eq!(parse(r#"x"y"#).unwrap(), r#""x" AND "y""#); // a quote starts a phrase
        assert_eq!(
            parse(r#""unclosed phrase"#).unwrap(),
            r#""unclosed phrase""#
        );
        assert_eq!(parse("Gemeinde - § 12").unwrap(), r#""Gemeinde" AND "12""#);
        assert_eq!(parse("abc**").unwrap(), r#""abc"*"#);
        assert_eq!(parse("Tempo-30 2,5").unwrap(), r#""Tempo-30" AND "2,5""#);
    }

    #[test]
    fn or_and_groups_and_near_are_operators() {
        assert_eq!(
            parse(r#"Kunstrasen* OR "gazon synthétique" OR "campo sintetico""#).unwrap(),
            r#""Kunstrasen"* OR "gazon synthétique" OR "campo sintetico""#
        );
        // AND binds more tightly than OR; parentheses group
        assert_eq!(parse("a b OR c").unwrap(), r#"("a" AND "b") OR "c""#);
        assert_eq!(
            parse("(Kunstrasen* OR Naturrasen) Kredit").unwrap(),
            r#"("Kunstrasen"* OR "Naturrasen") AND "Kredit""#
        );
        assert_eq!(
            parse("Kredit AND (a OR (b c))").unwrap(),
            r#""Kredit" AND ("a" OR ("b" AND "c"))"#
        );
        assert_eq!(parse("(a OR b").unwrap(), r#""a" OR "b""#); // runs to the end
        assert_eq!(parse("((a))").unwrap(), r#""a""#);
        assert_eq!(parse("(§) a").unwrap_err(), "a group ( ) has no word");
        assert_eq!(
            parse("NEAR(Kunstrasen* Kredit, 20)").unwrap(),
            r#"NEAR("Kunstrasen"* "Kredit", 20)"#
        );
        assert_eq!(
            parse(r#"Gemeinde NEAR ("Fr. 2,5" Kredit) OR x"#).unwrap(),
            r#"("Gemeinde" AND NEAR("Fr. 2,5" "Kredit")) OR "x""#
        );
        assert_eq!(parse("NEAR(a b,0)").unwrap(), r#"NEAR("a" "b", 0)"#);
        assert_eq!(parse("NEAR(a b").unwrap(), r#"NEAR("a" "b")"#);
        assert_eq!(parse("NEAR").unwrap(), r#""NEAR""#);
    }

    #[test]
    fn what_is_not_searched_as_typed_is_refused() {
        for q in ["*rasen", "Kunst*rasen", r#""*rasen""#, "x *y"] {
            assert_eq!(parse(q).unwrap_err(), STAR, "{q}");
        }
        for q in ["-Budget", "Tempo -30"] {
            assert_eq!(parse(q).unwrap_err(), MINUS, "{q}");
        }
        assert_eq!(parse("Budget NOT Konto").unwrap_err(), NOT);
        for q in [
            "OR",
            "OR x",
            "x OR",
            "x OR OR y",
            "AND x",
            "x AND",
            "x AND OR y",
            "(OR x)",
        ] {
            assert_eq!(parse(q).unwrap_err(), OPERAND, "{q}");
        }
        for q in ["x )", "(x))", ")"] {
            assert_eq!(parse(q).unwrap_err(), "a ) without its (", "{q}");
        }
        for q in ["NEAR(x)", "NEAR(x (y))", "NEAR(x OR y)", "NEAR(a b, 1001)"] {
            assert!(parse(q).is_err(), "{q}");
        }
        // the words inside NEAR count
        assert!(parse(&format!("NEAR({}) x", "w ".repeat(MAX_TERMS))).is_err());
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
            "()",
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

    fn marked_words(text: &str, highlights: &[[u32; 2]]) -> Vec<String> {
        let chars: Vec<char> = text.chars().collect();
        highlights
            .iter()
            .map(|[a, b]| chars[*a as usize..*b as usize].iter().collect())
            .collect()
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

    #[test]
    fn a_snippet_shows_the_different_words_even_when_they_are_far_apart() {
        let filler = "wort ".repeat(120);
        let marked = format!(
            "{OPEN}Kunstrasen{CLOSE} beim Schulhaus. {filler}Der {OPEN}Kredit{CLOSE} von Fr. \
             1,9 Mio. {filler}Noch einmal {OPEN}Kunstrasen{CLOSE}. {filler}"
        );
        let (text, highlights) = snippet(&marked);
        assert_eq!(marked_words(&text, &highlights), ["Kunstrasen", "Kredit"]);
        assert!(text.starts_with("Kunstrasen beim Schulhaus."), "{text}");
        assert!(text.contains(" … ") && text.ends_with('…'), "{text}");
        assert!(
            text.chars().count() <= SNIPPET_CHARS + 4 * WORD_EDGE + 4,
            "{text}"
        );
        // no passage cuts a word of the filler
        for word in text
            .split([' ', '…'])
            .filter(|w| w.chars().all(|c| "wort".contains(c)))
        {
            assert!(
                word.is_empty() || word == "wort",
                "a cut word: {word:?} in {text}"
            );
        }
        // when one passage shows every word, the snippet is that passage
        let near = format!("{filler}{OPEN}Kunstrasen{CLOSE} und {OPEN}Kredit{CLOSE} {filler}");
        let (text, highlights) = snippet(&near);
        assert_eq!(marked_words(&text, &highlights), ["Kunstrasen", "Kredit"]);
        assert!(!text.contains(" … ") && text.starts_with('…') && text.ends_with('…'));
    }
}
