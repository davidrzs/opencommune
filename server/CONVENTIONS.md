# Conventions

One binary crate (a library for the tests, a thin `main.rs`). It serves the JSON API, MCP and the
built front end from the SQLite database the Python package builds. Endpoints: `API.md`.

## Where things go

| What | Where |
| --- | --- |
| Start-up, configuration, logging | `src/main.rs`, `src/config.rs` (environment only) |
| Router, static files, layers | `src/lib.rs` (`app`) |
| Routes, one handler per endpoint | `src/routes/<area>.rs`, registered in `src/routes/mod.rs` |
| Queries, one function per endpoint | `src/db/<area>.rs` |
| Rows (`FromRow`) and JSON types (`Serialize`) | `src/models.rs` |
| MCP tools | `src/mcp.rs`, calling the same `db` functions |
| Pages for crawlers: shell, texts, rendering | `src/site.rs`; handlers in `src/routes/pages.rs` |
| Usage statistics | `src/usage.rs` |
| Errors | `src/error.rs` |
| Tables the Python build must write | `../src/opencommune/serving.sql` |
| Integration tests | `tests/api.rs`, fixture databases created in the test |

## Rules

1. Read-only. The archive database is opened read-only; the only file the server writes is the
   usage database.
2. No caches. Anything slow becomes a table or an index in the Python build, not memory here.
   Every list query is backed by an index; a new list query names its index in `API.md`.
3. Runtime queries: `sqlx::query_as` with `FromRow` structs, `QueryBuilder` for optional
   filters. No compile-time database checking. Values are always bound, never formatted into SQL.
4. Handlers parse and validate, call one `db` function and return JSON. No SQL in handlers.
5. Errors are JSON, `{"detail": "..."}`. Database errors are logged and answer 500 without
   details.
6. A change of a response's shape is recorded in `API.md`.
7. Logging through `tracing`; no `println!`. Never log raw paths, query strings, search terms or
   client addresses; the request span carries the route template.
8. Data protection: lists link documents through `/original/<sha256>`; no unreviewed titles. Until
   `SEARCH_INDEXING` is on, every response carries `noindex, nofollow`.
9. Crawlers: training crawlers are refused in `robots.txt`; search engines and AI assistants get
   the same HTML as every visitor, with the page's facts in it (`src/site.rs`).

## Checks

```sh
cargo fmt --check
cargo clippy --all-targets -- -D warnings
cargo test
```
