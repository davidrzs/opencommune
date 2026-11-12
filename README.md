# OpenCommune

An open archive of the decisions of Swiss municipalities: Gemeindeversammlung, Gemeindeparlament,
Conseil communal and Consiglio comunale minutes, and other public municipal documents such as
budgets, accounts and vote results. Documents are collected directly from municipal websites,
structured with a language model, anonymised, and served as a website, a JSON API and an MCP server
for AI agents. No API key. Public site: https://www.opencommune.ch.

## Parts

1. **Server** (Rust, `server/`): the JSON API, MCP over streamable HTTP at `/mcp`, and the static
   website. It reads a SQLite database only. Details in `server/API.md`.
2. **Website** (SvelteKit, `frontend/`): built to static files that the server serves.
3. **Crawler and processing** (Python): collect the documents and build the database. They are
   being moved into this repository.

## Run it

Requirements: Rust (stable) and Node 22, and a database built by the processing stages.

```sh
(cd frontend && npm ci && npm run build)          # frontend/build
(cd server && cargo build --release)              # server/target/release/opencommune-server
DATABASE_PATH=opencommune.db STATIC_DIR=frontend/build \
  server/target/release/opencommune-server        # http://127.0.0.1:8000
```

Deploying it behind Caddy: `deploy/server/README.md`.

## Data protection

Decisions on naturalisation, social assistance, guardianship, health and identifiable personnel
matters are dropped; names of private individuals are replaced with `[Person]`; office holders stay
named. The website does not serve copies of the documents: it links to the originals through a
redirect, never lists unreviewed titles or document URLs, and leaves out documents whose title or
URL marks them as naturalisation documents.

## Development

`cargo test` in `server/`, and `npm run check` and the offline Playwright test in `frontend/`
(`frontend/README.md`). CI runs all of them. Conventions are in `AGENTS.md`.

## Licence

- Code: MIT (`LICENSE`).
- Data: the records OpenCommune extracts are released under
  [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/): free to use for any purpose,
  without conditions. Strictly speaking you need not cite OpenCommune, but a citation is highly
  appreciated.
- Map: boundaries from swisstopo through the
  [swiss-maps](https://github.com/interactivethings/swiss-maps) package.
