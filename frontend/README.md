# Svelte frontend

SvelteKit/Svelte 5 single-page app with TypeScript and a native SVG map. It is built to static
files (`@sveltejs/adapter-static`, fallback `index.html`) that the Rust server in `../server`
serves together with the JSON API on the same origin. Node is needed only to build.

## Run locally

Start the Rust server against a database (`../server/API.md`):

```sh
cd server && DATABASE_PATH=../data/opencommune.db cargo run
```

In another terminal:

```sh
cd frontend
npm ci
npm run dev
```

Open http://127.0.0.1:5173/de (or `/fr`, `/it`). Vite proxies `/api` and `/original` to
`API_ORIGIN` (default http://127.0.0.1:8000). Pages load their data in the browser with universal
`+page.ts` / `+layout.ts` loaders: the commune list (`/api/communes`) once for the map and the
search, one commune (`/api/communes/{bfs}`) and a page of its files (`/api/documents`) on its page,
the classification runs (`/api/runs`) on the about page.

To serve the built site: `npm run build`, then run the server with `STATIC_DIR=frontend/build`.

## What works

- Map-first homepage with the number of files and communes, commune-name search and canton index
  filter. Communes whose register status is `blocked_robots` are hatched.
- Addressable commune archives (`/{lang}/gemeinden/{bfs}`): a holdings table (documents per year
  and section family; a cell filters the list), then the commune's files. Each file shows its
  printed title, body, pages, languages that differ from the page's, and its sections: a contents
  line and a page strip in the six family colours, and chips that open the original at the
  section's first page. Selectors with counts (section type, body, year) and a title text field;
  filtering by a section type or family shows the matching sections as lines of their own. Pages
  of 20; the filters live in the URL query. Under the list, the exact `/api/documents` request.
- The same list across all communes (`/{lang}/suche`), each file with its communes.
- The about page explains each classification run from `/api/runs`; files link to their run.
- The API page (`/{lang}/api`): what the API is, the MCP address with a configuration snippet,
  and an interactive reference from `/api/openapi.json` ([Scalar](https://github.com/scalar/scalar),
  MIT, self-hosted). It is loaded only on that page (about 4 MB, 1.1 MB gzipped) and sends nothing
  to other origins: no Scalar fonts, proxy, telemetry, AI agent or developer tools, and "try it"
  goes to this site.
- German, French and Italian interface dictionaries, locale-aware numbers/dates, preserved
  page/query when switching language, correct HTML language on every navigation.
- Responsive desktop/mobile layouts, keyboard links/search, focus states, reduced motion.

Map geometry comes from swisstopo through the swiss-maps package (`scripts/build_map.py`); no
map library. Shared UI components and translations live in `src/lib`.
[SvelteKit's routing](https://svelte.dev/docs/kit/routing) supplies navigation and page loading.

## Checks

```sh
npm run check
npm run build
npx playwright install chromium --only-shell
npx playwright test --config playwright.access.config.ts  # static build against an offline API fixture
npx playwright test  # smoke test: needs the Rust server on a real database and the Vite dev server
npm run format:check
```

CI runs `check`, `format:check`, `build` and the offline tests (`access.spec.ts`,
`documents.spec.ts`, `api.spec.ts` against `tests/access-fixture.py`, which serves a saved copy of
the server's `openapi.json` from `tests/openapi.json`). The smoke test needs real data (it opens
Wetzikon, BFS 121, and expects files there), so it runs only by hand.
Screenshots go to the ignored `test-results/` directory.

## Limits

UI translations do not translate source material or enable cross-language semantic search.
Romansh and English are not yet provided. File contents are not searched: the text field matches
the printed titles. Titles, bodies, dates and sections come from a language model and are not
checked by a person; private names in titles appear as "[name]". `personal_data` is never shown.

## Deployment

The server binary serves `frontend/build` (`STATIC_DIR`): files as they are, `index.html` for
every other path, hashed `_app/immutable` files with a one-year cache. Every page carries
`noindex, nofollow`. Usage statistics are counted by the server: page loads of
`index.html` by route template, API requests by route; client-side navigation is not a page
load.

Problem reports open a user-controlled mail draft with the page, record ID and source.
The recipient is assembled on click; obfuscation only deters basic HTML scraping.
