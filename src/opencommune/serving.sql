-- Serving tables `opencommune build` writes into the main database next to `communes`,
-- `documents`, `decisions`, `decisions_fts`, `holdings` and `pdf_catalog`. The Rust server reads
-- them only; it never reads YAML or JSON files. Its integration tests create them from this file.

-- The coverage register (data/register/<CANTON>.yaml), one row per commune.
CREATE TABLE IF NOT EXISTS register (
    bfs_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    canton TEXT NOT NULL,
    status TEXT NOT NULL,
    website TEXT,
    vendor TEXT,
    reachable INTEGER,          -- 1, 0 or NULL
    checked TEXT,               -- ISO date
    checked_by TEXT,
    notes TEXT,
    -- The note the commune list shows (build.register_note).
    note TEXT
);
CREATE INDEX IF NOT EXISTS register_canton ON register (canton, bfs_id);

-- The register's publications, in file order.
CREATE TABLE IF NOT EXISTS register_publications (
    bfs_id INTEGER NOT NULL,
    position INTEGER NOT NULL,
    body TEXT NOT NULL,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    listing_url TEXT,
    "from" TEXT,
    "to" TEXT,
    cadence TEXT,
    obstacle TEXT,
    how TEXT,
    PRIMARY KEY (bfs_id, position)
) WITHOUT ROWID;

-- Current access failures, one row per commune and website: the latest check of any address on
-- the host, attributed to the one register commune whose website is there. The row links to the
-- website, never to a document.
CREATE TABLE IF NOT EXISTS access_observations (
    bfs_id INTEGER NOT NULL,
    source_url TEXT NOT NULL,   -- scheme://host/
    status TEXT NOT NULL,       -- restricted | rate_limited | robots_unavailable | technical_error
    checked_at TEXT NOT NULL,   -- ISO timestamp with offset
    robots_url TEXT NOT NULL,
    restricted_at TEXT
);
CREATE INDEX IF NOT EXISTS access_observations_commune
    ON access_observations (bfs_id, checked_at DESC);

-- Indexes on the decision and catalogue tables, for the server's queries.
CREATE INDEX IF NOT EXISTS decisions_document ON decisions (document_id);
CREATE INDEX IF NOT EXISTS pdf_catalog_commune_date ON pdf_catalog (commune_bfs_id, source_date);
