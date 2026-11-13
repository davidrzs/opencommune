# API

The JSON API, MCP and the static front end, served from the serving database the Python build
writes (`src/opencommune/serving.sql`). No key; every response carries
`X-Robots-Tag: noindex, nofollow` until `SEARCH_INDEXING` is on.

## Running

```sh
cd frontend && npm ci && npm run build          # Node is needed only to build
cd server && cargo build --release
DATABASE_PATH=data/opencommune.db STATIC_DIR=frontend/build server/target/release/opencommune-server
```

| Variable | Default | Meaning |
| --- | --- | --- |
| `DATABASE_PATH` | `data/opencommune.db` | serving database, opened read-only; the server does not start without its tables |
| `STATIC_DIR` | `frontend/build` | built front end; `index.html` answers every other path |
| `BIND` | `127.0.0.1:8000` | listen address |
| `USAGE_PATH` | `data/logs/usage.sqlite3` | usage statistics (writable, separate file) |
| `USAGE_ENABLED` | `true` | `false`: count nothing |
| `USAGE_VISITORS` | `true` | daily visitor estimate |
| `MCP_ALLOWED_HOSTS` | `localhost,127.0.0.1,::1` | `Host` values `/mcp` accepts; add the public domains |
| `PUBLIC_URL` | `http://` + `BIND` | the site's address in canonical links, the sitemap and `llms.txt` |
| `SEARCH_INDEXING` | `false` | `true`: search engines may index the pages; `false`: every response says `noindex` |
| `RUST_LOG` | `info,rmcp=warn` | log filter; `debug` logs one line per request (route template only) |

`DATASET_PATH` is no longer read.

## Endpoints

| Endpoint | Used by |
| --- | --- |
| `GET /api/communes` | map and commune list, MCP `list_communes` |
| `GET /api/communes/{bfs_id}` | commune page |
| `GET /api/documents` | document lists and search, MCP `search_documents` |
| `GET /api/documents/{sha256}` | one document, MCP `get_document` |
| `GET /api/runs` | the runs behind the classification |
| `GET /api/openapi.json` | the OpenAPI 3.1 description of this API, for tools and the website's API page |
| `GET /api/register` | API users |
| `GET /original/{sha256}` | links in document lists |
| `POST /mcp` | AI agents |
| `GET /robots.txt`, `/sitemap.xml`, `/llms.txt` and the pages below | search engines, AI assistants |

Errors are JSON, `{"detail": "..."}`; invalid parameters answer 400, unknown `/api/...` paths 404.
Dates are `YYYY-MM-DD`.

### `GET /api/communes`

Every commune of the `communes` table, by canton and name: `bfs_id, name, canton, language,
website, lat, lon, documents, register_status, register_note`. `documents` is the commune's number
of rows in `document_communes`; a document several communes link counts for each.
`register_status` and `register_note` are the commune's `register` row's `status` and `note`, null
without a row. Communes only in the register are not listed.

### `GET /api/communes/{bfs_id}`

`bfs_id, name, canton, language, website, vendor, lat, lon, documents, register, access,
holdings`.
`register` is the commune's entry as in `/api/register`, or null. `access` is
`[{status, checked_at, robots_url, restricted_at, source_url, stale}]`, one entry per website,
newest check first; `source_url` is the website, never a document; an entry is `stale` when its
`restricted_at` (or `checked_at`) is 7 days old or more, computed at request time. 404 when the
commune is not in the `communes` table. `holdings` is `[{year, family, documents}]`: per year and
section family, how many of the commune's documents of that year have a section of that family;
newest year first, then family. Documents without a year are not counted.

### `GET /api/documents`

Parameters, all optional; filters combine with AND, and a blank text filter is no filter:

1. `commune`: a BFS id; the documents the commune links (`document_communes`).
2. `section`: documents with at least one section of this type.
3. `family`: documents with at least one section of this family.
4. `body`: `documents.body_kind`.
5. `year`: `documents.year` (the year of `date`, else the one year in `years`, else of
   `listing_date`).
6. `q`: text the title contains, case-insensitive for ASCII (SQLite `lower`); `%` and `_` are
   plain characters.
7. `limit`: 0 to 100, default 20; `0` gives the total and the facets only.
8. `offset`: 0 or more, default 0.

```json
{"total": 0, "offset": 0, "limit": 20,
 "facets": {"years": [Count], "sections": [Count], "bodies": [Count]},
 "items": [Document]}
```

Order: `year` descending with no year last, then `date` (else `listing_date`) descending, then
`sha256`.

`Count` is `{value, count}`: how many of the matching documents have the value. Each facet is
counted with every filter applied except its own (`years` without `year`, `sections` without
`section`, `bodies` without `body`; `family` and `q` apply to every facet). Values are in ascending order, years newest first; a
NULL value is `"value": null` and comes last. `sections` counts documents, not sections: a document
with two sections of a type counts once, and a document without sections is in no entry.

`Document`: `sha256, title, body_name, first_seen, listing_date, date, year, years[int], page_count,
pages_seen, run_id, body_kind, languages[str], personal_data,
sections[{type, family, first_page, last_page, partly_unseen}], communes[{bfs_id, name, canton}],
original_url`. Every document is classified; files without an answer are not in the database.

1. `years` and `languages` are the comma-separated columns as lists, `[]` when NULL; a part of
   `years` that is not an integer is left out.
2. `title` and `body_name` are as printed, as the classifier read them, with private names written
   as `[name]`; null when the pages show none. `personal_data` is `true` or `false`; the website
   never shows it.
3. `sections` are in the classifier's order (`position`); `communes` are by name.
4. `original_url` is always `/original/<sha256>`, never a commune's URL. It answers 404 when no
   commune gives the document a linkable URL. `?commune=<bfs_id>` picks that commune's link and
   `?page=<n>` adds `#page=<n>`, which PDF viewers open at that page.
5. `title`, `body_name`, `body_kind`, `date`, `years`, `languages`, `personal_data` and `sections` come from an
   automatic classification that no person has checked yet; `run_id` names the run.

### `GET /api/documents/{sha256}`

The `Document` with `run`: `{id, stage, model, note}` of `run_id`, or null. 404 when unknown.

### `GET /api/openapi.json`

The OpenAPI 3.1 description of the endpoints above. Its schemas are generated from the same Rust
types the handlers read and return (`src/routes/openapi.rs`); a test fails when a route of the
router is missing from it or its fields differ from what the API sends.

### `GET /api/runs`

Every run, by id: `id, stage, model, settings, note, documents`. `settings` is the stored JSON
object (null if it does not parse); `note` says in plain sentences what the settings do to the data.

### `GET /api/register`

Every register row, by canton and BFS id: `bfs_id, name, canton, status, website, vendor,
reachable, checked, checked_by, notes, publications[{body, kind, status, listing_url, from, to,
cadence, obstacle, how}]`.

### `GET /original/{sha256}?commune=<bfs_id>`

302 to the document on a commune's site, with `X-Robots-Tag: noindex, nofollow`: the `source_url`
the commune gives it in `document_communes`; without `commune`, or when that commune gives no
linkable URL, the first by BFS id. Only absolute http(s) URLs are used; 404 when there is none.

### `POST /mcp`

Streamable HTTP, stateless (no session kept), JSON responses. Tools:

1. `list_communes()`: as `/api/communes`, wrapped as `{"result": [...]}`.
2. `search_documents(commune, section, family, body, year, q, offset, limit)`: the parameters and
   the result of `/api/documents`; an offset or limit out of range is a tool error with a reason.
3. `get_document(sha256)`: as `/api/documents/{sha256}`; `{"error": "not found"}` when unknown.

The descriptions of `search_documents` and `get_document` say that titles, bodies, dates and sections
come from an automatic classification that no person has checked yet. Every tool has a title and is
marked read-only (`readOnlyHint`). Results are `structuredContent` plus the same JSON as text.

## Pages for search engines and AI assistants

The front end renders in the browser. For the pages below the server puts the facts into the HTML
it sends: title, description, canonical link, links to the other two languages, schema.org JSON-LD
where it fits, and a fact sheet in `<main id="oc-facts">` that the app replaces on start. Every
visitor receives the same HTML.

1. `/{lang}` (`de`, `fr`, `it`): the number of documents and of the communes that link them (with
   the note that no person has checked the classification), and the communes with documents
   (JSON-LD `Dataset`). `/` redirects to `/de`.
2. `/{lang}/gemeinden/{bfs_id}`: the commune's number of documents, website, documents per year
   and the first page of `/api/documents?commune=<bfs_id>` (the twenty newest documents, title and
   date, linked through `/original/<sha256>?commune=<bfs_id>`) (JSON-LD `AdministrativeArea`). 404
   when the commune is not in the `communes` table.
3. `/{lang}/ueber-uns`, `/{lang}/datenschutz`; `/{lang}/suche` (never indexed).
4. `/robots.txt`: crawlers that collect training data (GPTBot, ClaudeBot, CCBot, Google-Extended
   and others) may read nothing; all others may read the pages but not `/api/`, `/mcp`,
   `/original/` or the search. Lists the sitemap when `SEARCH_INDEXING` is on.
5. `/sitemap.xml`: the start, about and privacy pages and every commune of the `communes` table, in
   the three languages.
6. `/llms.txt`: a Markdown guide for AI agents (llmstxt.org) with the current totals, the MCP
   address and the API.

## Tables and indexes

The server reads the tables of `src/opencommune/serving.sql` only: `communes`, `runs`,
`documents`, `document_communes`, `sections`, `register`, `register_publications` and
`access_observations`. `opencommune build` writes them from scratch; the integration tests create
their database from the same file. The build leaves the database out of WAL mode, so the read-only
server needs no `-shm` file.

| Query | Index |
| --- | --- |
| `documents` count per commune, `commune` filter | `document_communes_commune` |
| `section` filter, `sections` facet | `sections_type` |
| `year` filter, `years` facet, the order's first key | `documents_year` |
| a page's sections and communes, `/original` | the primary keys of `sections` and `document_communes` |
| access observations of a commune | `access_observations_commune` |

The `bodies` facet and the `q` filter read the whole `documents`
table (or what the other filters leave of it). On a synthetic database of the archive's size
(360,000 documents, 650,000 sections) `/api/documents` without filters takes about 0.65 s, with
`q` about 1.2 s; with `commune` or `year` it takes under 0.1 s. Deep pages are slow too: an offset
of 300,000 takes about 1 s.
