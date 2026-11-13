# API

The JSON API, MCP and the static front end, served from the SQLite database the Python pipeline
builds. No key; every response carries
`X-Robots-Tag: noindex, nofollow`.

## Running

```sh
cd frontend && npm ci && npm run build          # Node is needed only to build
cd server && cargo build --release
DATABASE_PATH=data/opencommune.db STATIC_DIR=frontend/build server/target/release/opencommune-server
```

| Variable | Default | Meaning |
| --- | --- | --- |
| `DATABASE_PATH` | `data/opencommune.db` | archive database, opened read-only |
| `STATIC_DIR` | `frontend/build` | built front end; `index.html` answers every other path |
| `BIND` | `127.0.0.1:8000` | listen address |
| `USAGE_PATH` | `data/logs/usage.sqlite3` | usage statistics (writable, separate file) |
| `USAGE_ENABLED` | `true` | `false`: count nothing |
| `USAGE_VISITORS` | `true` | daily visitor estimate |
| `DATASET_PATH` | unset | optional dataset SQLite; unset, `/api/dataset/*` answers 404 |
| `MCP_ALLOWED_HOSTS` | `localhost,127.0.0.1,::1` | `Host` values `/mcp` accepts; add the public domains |
| `PUBLIC_URL` | `http://` + `BIND` | the site's address in canonical links, the sitemap and `llms.txt` |
| `SEARCH_INDEXING` | `false` | `true`: search engines may index the pages; `false`: every response says `noindex` |
| `RUST_LOG` | `info,rmcp=warn` | log filter; `debug` logs one line per request (route template only) |

## Endpoints

| Endpoint | Used by |
| --- | --- |
| `GET /api/decisions` | search page, commune page, MCP |
| `GET /api/decisions/{id}` | decision page, MCP, API users |
| `GET /api/documents` | API users |
| `GET /api/stats` | API users |
| `GET /api/communes` | MCP `list_communes`, API users |
| `GET /api/register` | API users |
| `GET /api/archive/communes` | map and commune search |
| `GET /api/archive/communes/{bfs_id}` | commune page |
| `GET /api/archive/documents` | commune page, documents tab |
| `GET /original/{sha256}` | links in document lists |
| `GET /api/dataset/communes/{bfs_id}`, `/api/dataset/coverage`, `/api/dataset/findings` | commune and start pages |
| `POST /mcp` | AI agents |
| `GET /robots.txt`, `/sitemap.xml`, `/llms.txt` and the pages below | search engines, AI assistants |

Errors are JSON, `{"detail": "..."}`; invalid parameters answer 422, unknown `/api/...` paths 404.
Dates are `YYYY-MM-DD`.

### `GET /api/decisions`

Parameters: `q` (free text), `commune` (BFS id), `canton`, `category`, `outcome`, `lang`, `body`,
`from`, `to` (ISO dates), `min_amount`, `limit` (1..200, default 20), `offset` (>= 0).
Full-text search (`decisions_fts`, FTS5, diacritics removed) when `q` has at least 3 characters
and finds something; otherwise `LIKE` on title and summary; without `q` the newest decisions.

```json
{"total": 0, "mode": "recent|fts|like", "limit": 20, "offset": 0, "items": [Decision]}
```

`Decision`: `id, title, summary, category, outcome, agenda_no, meeting_date, votes_for,
votes_against, amount_chf, references[], office_holders[], page_start, page_end, language,
confidence, contains_private_individuals, redaction_applied, extraction_model,
extraction_version, commune{bfs_id,name,canton}, document{id,body,source_url,provenance,sha256,
pages,title}, source_link`. `source_link` is the document on the commune's site at the cited page;
published records keep their direct source links.

### `GET /api/documents`

Parameters: `commune`, `body`. Published documents, newest meeting first: `id,
commune{bfs_id,name,canton}, body, meeting_date, language, pages, ocr, title, source_url,
provenance, sha256, decisions, dropped_decisions, fetched_at`.

### `GET /api/stats`

`communes, communes_with_decisions, communes_in_register, register{communes, by_status{...10
statuses}, blocked, examined, reachable, unreachable}, by_health{}, documents, decisions,
decisions_dropped_for_privacy, decisions_redacted, date_min, date_max, approved_amount_chf,
by_canton[{canton,communes,documents,decisions}], by_category[{category,decisions}],
by_outcome{}, by_language{}, by_body{}, extraction_models{}, categories[]`. A null key is
written `"None"`.

`communes_in_register` is the register's row count (one row per BFS commune while
`opencommune register check` passes).

### `GET /api/communes`

Every commune of the `communes` table, by canton and name: `bfs_id, name, canton, language,
website, vendor, minutes_url, publicity_regime, last_crawled, lat, lon, documents, decisions,
holdings[Holding], register_status, register_note`. `Holding` is a row of the `holdings` table
(`body, kinds, documents, undated, parsed, extracted, records, decisions, first_date, last_date,
per_year, per_year_average, expected_interval_days, gaps, stale, listed_not_held, last_crawl,
last_result, health, register_status, register_note, available_from`).

### `GET /api/register`

Every register row, by canton and BFS id: `bfs_id, name, canton, status, website, vendor,
reachable, checked, checked_by, notes, publications[{body, kind, status, listing_url, from, to,
cadence, obstacle, how}]`.

### `GET /api/archive/communes` and `/api/archive/communes/{bfs_id}`

1. The list: `bfs_id, name, canton, lat, lon, documents, decisions, access`, for every commune
   of the `communes` table and of the register. `access` is one state: `restricted` while a
   website refuses the crawler, `earlier` once that restriction is a week old, `temporary` for
   other failures (rate limits, robots.txt or technical errors); absent when every check passed.
2. The detail: the `/api/communes` row with `documents` from the catalogue and
   `access[{status, checked_at, robots_url, restricted_at, source_url, stale}]`, one entry per
   website, newest check first; `source_url` is the website, never a document. A commune only in
   the register has `bfs_id, name, canton, website, documents: 0, decisions: 0, holdings: [],
   access`. 404 when unknown.

`documents` is the catalogue count once `pdf_catalog` has rows, else the holdings' sum, else the
published documents. An entry is `stale` when its `restricted_at` (or `checked_at`) is 7 days old
or more, computed at request time.

### `GET /api/archive/documents`

Parameters: `commune`, `q` (title contains, case-insensitive for ASCII as SQLite `lower`), `year`
(1800..2200), `offset`. Pages of 20, newest first:
`{"total", "years": [newest..oldest], "items": [{id, title, date, status, decisions, url, body}]}`.
`url` is `/original/<sha256>`, never the commune's URL; null when the stored URL
is not absolute http(s). Titles are the catalogue's fixed labels or published titles. Naturalisation documents are not in `pdf_catalog` (the catalogue build leaves them out).

### `GET /original/{sha256}`

302 to the document on the commune's site (its `source_url`, if absolute
http(s)), with `X-Robots-Tag: noindex, nofollow`; 404 otherwise.

### `/api/dataset/*`

Read from the optional dataset SQLite at `DATASET_PATH` (votes and finances per commune; its build
is not part of this repository yet). Rows go to JSON with SQLite's value types.

1. `communes/{bfs_id}`: `{meetings[], votes[] (+ formal), finance[], summary{meetings,
   median_turnout, counted, decided, rejected}}`; votes flagged `possible_duplicate` are left out;
   withheld titles stay null.
2. `coverage`: `{communes[{bfs_id, minutes, counted, finance_years}], totals{communes,
   communes_with_minutes, communes_with_finance, population_share, minutes, counted}}`.
3. `findings`: `{deficits[{year, type, deficit, n}] (2018-2025), turnout_by_size[{min, max,
   median, n}]}`.

The server opens the file at start; a file that appears later needs a restart.

### `POST /mcp`

Streamable HTTP, stateless (no session kept), JSON responses. Tools: `search_decisions(query, commune_bfs_id, canton, category,
outcome, language, date_from, date_to, min_amount_chf, limit<=100)`, `get_decision(decision_id)`,
`list_communes()`. Every tool has a title and is marked read-only (`readOnlyHint`). Results are
`structuredContent` plus the same JSON as text; `list_communes` wraps its list as
`{"result": [...]}`. A bad date is a tool error with a reason.

## Pages for search engines and AI assistants

The front end renders in the browser. For the pages below the server puts the facts into the HTML
it sends: title, description, canonical link, links to the other two languages, schema.org JSON-LD
where it fits, and a fact sheet in `<main id="oc-facts">` that the app replaces on start. Every
visitor receives the same HTML.

1. `/{lang}` (`de`, `fr`, `it`): the archive's totals and the communes with decisions (JSON-LD
   `Dataset`). `/` redirects to `/de`.
2. `/{lang}/gemeinden/{bfs_id}`: the commune's counts, website and twenty newest decisions
   (JSON-LD `AdministrativeArea`). 404 when the commune is unknown.
3. `/{lang}/entscheide/{id}`: one decision with commune, date, outcome, amount, summary and the
   link to its page in the source PDF. 404 when unknown.
4. `/{lang}/ueber-uns`, `/{lang}/datenschutz`; `/{lang}/suche` (never indexed).
5. `/robots.txt`: crawlers that collect training data (GPTBot, ClaudeBot, CCBot, Google-Extended
   and others) may read nothing; all others may read the pages but not `/api/`, `/mcp`,
   `/original/` or the search. Lists the sitemap when `SEARCH_INDEXING` is on.
6. `/sitemap.xml`: the start, about and privacy pages, every commune with documents or decisions and every
   decision, in the three languages.
7. `/llms.txt`: a Markdown guide for AI agents (llmstxt.org) with the current totals, the MCP
   address, the API and the dataset.

## Tables

The server reads `communes`, `documents`, `decisions`, `decisions_fts`, `holdings` and
`pdf_catalog` (written by the processing stages and `opencommune catalog`) and `register`, `register_publications` and
`access_observations` (written by `opencommune build`, DDL in `src/opencommune/serving.sql`, which
the integration tests also use). These are a snapshot: a register edit shows after the next build.
The build leaves the database out of WAL mode, so the read-only server needs no `-shm` file.
Searching titles across the whole catalogue (`/api/archive/documents?q=` without `commune`) is a
full scan; the front end always passes `commune`.
