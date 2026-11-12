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
`+page.ts` / `+layout.ts` loaders: the slim commune list (`/api/archive/communes`) once for the
map and the search, one commune (`/api/archive/communes/{bfs}`) on its page.

To serve the built site: `npm run build`, then run the server with `STATIC_DIR=frontend/build`.

## What works

- Map-first homepage, real PDF/decision coverage, commune-name search and canton index filter.
- Addressable commune archives (`/{lang}/gemeinden/{bfs}`), PDF/decision tabs, title/year
  filters, pagination and original-source links. Decision links retain source page numbers.
- Topic search (`/{lang}/suche`) across extracted decisions in their original languages.
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

CI runs `check`, `format:check`, `build` and the offline access test. The smoke test needs real
data (it opens Wetzikon, BFS 121, and expects decisions there), so it runs only by hand.
Screenshots go to the ignored `test-results/` directory.

## Limits

UI translations do not translate source material or enable cross-language semantic search.
Romansh and English are not yet provided. Unparsed PDF contents are not full-text indexed;
PDF search currently searches stored titles. Generic documents retain a translated generic
label rather than exposing raw filenames or inventing titles.

## Deployment

The server binary serves `frontend/build` (`STATIC_DIR`): files as they are, `index.html` for
every other path, hashed `_app/immutable` files with a one-year cache. Every page carries
`noindex, nofollow`. Usage statistics are counted by the server: page loads of
`index.html` by route template, API requests by route; client-side navigation is not a page
load.

Problem reports open a user-controlled mail draft with the page, record ID and source.
The recipient is assembled on click; obfuscation only deters basic HTML scraping.
