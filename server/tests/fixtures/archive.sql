-- The archive tables as the Python package creates them (models.py, db.py), for the tests.
CREATE TABLE communes (
	bfs_id INTEGER NOT NULL,
	name VARCHAR(120) NOT NULL,
	canton VARCHAR(2) NOT NULL,
	language VARCHAR(2) NOT NULL,
	website VARCHAR(255) NOT NULL,
	vendor VARCHAR(60),
	minutes_url VARCHAR(500),
	publicity_regime VARCHAR(60),
	last_crawled DATETIME,
	lat FLOAT,
	lon FLOAT,
	PRIMARY KEY (bfs_id)
);
CREATE INDEX ix_communes_canton ON communes (canton);
CREATE TABLE documents (
	id VARCHAR(36) NOT NULL,
	commune_bfs_id INTEGER NOT NULL,
	body VARCHAR(20) NOT NULL,
	source_url VARCHAR(500) NOT NULL,
	sha256 VARCHAR(64) NOT NULL,
	fetched_at DATETIME NOT NULL,
	meeting_date DATE,
	language VARCHAR(2) NOT NULL,
	pages INTEGER NOT NULL,
	ocr BOOLEAN NOT NULL,
	title VARCHAR(300) NOT NULL,
	dropped_decisions INTEGER NOT NULL,
	provenance VARCHAR(30) NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(commune_bfs_id) REFERENCES communes (bfs_id),
	UNIQUE (sha256)
);
CREATE INDEX ix_documents_meeting_date ON documents (meeting_date);
CREATE INDEX ix_documents_commune_bfs_id ON documents (commune_bfs_id);
CREATE TABLE decisions (
	rid INTEGER NOT NULL,
	id VARCHAR(36) NOT NULL,
	document_id VARCHAR(36) NOT NULL,
	commune_bfs_id INTEGER NOT NULL,
	meeting_date DATE,
	agenda_no VARCHAR(40),
	title TEXT NOT NULL,
	category VARCHAR(30) NOT NULL,
	sensitive_topic VARCHAR(30) NOT NULL,
	summary TEXT NOT NULL,
	outcome VARCHAR(20),
	votes_for INTEGER,
	votes_against INTEGER,
	amount_chf FLOAT,
	refs JSON NOT NULL,
	office_holders JSON NOT NULL,
	page_start INTEGER NOT NULL,
	page_end INTEGER NOT NULL,
	confidence FLOAT,
	contains_private_individuals BOOLEAN NOT NULL,
	redaction_applied BOOLEAN NOT NULL,
	extraction_model VARCHAR(60) NOT NULL,
	extraction_version VARCHAR(30) NOT NULL,
	language VARCHAR(2) NOT NULL,
	PRIMARY KEY (rid),
	FOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE CASCADE,
	FOREIGN KEY(commune_bfs_id) REFERENCES communes (bfs_id)
);
CREATE INDEX ix_decisions_category ON decisions (category);
CREATE UNIQUE INDEX ix_decisions_id ON decisions (id);
CREATE INDEX ix_decisions_commune_date ON decisions (commune_bfs_id, meeting_date);
CREATE INDEX ix_decisions_meeting_date ON decisions (meeting_date);
CREATE VIRTUAL TABLE decisions_fts USING fts5(
        title, summary,
        content='decisions', content_rowid='rid',
        tokenize='unicode61 remove_diacritics 2'
    );
CREATE TRIGGER decisions_ai AFTER INSERT ON decisions BEGIN
        INSERT INTO decisions_fts(rowid, title, summary) VALUES (new.rid, new.title, new.summary);
    END;
CREATE TRIGGER decisions_ad AFTER DELETE ON decisions BEGIN
        INSERT INTO decisions_fts(decisions_fts, rowid, title, summary)
        VALUES ('delete', old.rid, old.title, old.summary);
    END;
CREATE TRIGGER decisions_au AFTER UPDATE ON decisions BEGIN
        INSERT INTO decisions_fts(decisions_fts, rowid, title, summary)
        VALUES ('delete', old.rid, old.title, old.summary);
        INSERT INTO decisions_fts(rowid, title, summary) VALUES (new.rid, new.title, new.summary);
    END;
CREATE TABLE holdings (
	commune_bfs_id INTEGER NOT NULL,
	body VARCHAR(20) NOT NULL,
	kinds JSON NOT NULL,
	documents INTEGER NOT NULL,
	undated INTEGER NOT NULL,
	parsed INTEGER NOT NULL,
	extracted INTEGER NOT NULL,
	records INTEGER NOT NULL,
	decisions INTEGER NOT NULL,
	first_date DATE,
	last_date DATE,
	per_year JSON NOT NULL,
	expected_interval_days FLOAT,
	gaps JSON NOT NULL,
	stale BOOLEAN NOT NULL,
	listed_not_held INTEGER NOT NULL,
	last_crawl DATETIME,
	last_result VARCHAR(40),
	health VARCHAR(20) NOT NULL,
	register_status VARCHAR(30),
	register_note TEXT,
	available_from VARCHAR(10),
	computed_at DATETIME NOT NULL,
	PRIMARY KEY (commune_bfs_id, body)
);
CREATE TABLE pdf_catalog (
	sha256 VARCHAR(64) NOT NULL,
	commune_bfs_id INTEGER NOT NULL,
	commune_name VARCHAR(120) NOT NULL,
	canton VARCHAR(2) NOT NULL,
	body VARCHAR(20) NOT NULL,
	source_date DATE,
	date_precision VARCHAR(10) NOT NULL,
	title TEXT NOT NULL,
	source_url TEXT,
	provenance VARCHAR(30) NOT NULL,
	status VARCHAR(30) NOT NULL,
	decision_count INTEGER NOT NULL,
	indexed_at DATETIME NOT NULL,
	PRIMARY KEY (sha256)
);
CREATE INDEX ix_pdf_catalog_canton ON pdf_catalog (canton);
CREATE INDEX ix_pdf_catalog_source_date ON pdf_catalog (source_date);
CREATE INDEX ix_pdf_catalog_commune_bfs_id ON pdf_catalog (commune_bfs_id);
CREATE INDEX ix_pdf_catalog_status ON pdf_catalog (status);
