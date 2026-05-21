-- pf_* schema, owned by personal-finance.
-- Applied inside a single sqlite3 transaction by
-- src/pf_skill/common/store.py when pf_schema_version reports a version
-- below 1. The applier loads this file via importlib.resources from the
-- in-package mirror at src/pf_skill/schema/ and executes each statement
-- inside an explicit BEGIN/COMMIT so the whole migration is atomic.
--
-- This top-level copy is committed for convenience (visibility in the
-- repo root and CLAUDE.md grep-ability). The authoritative location at
-- runtime is src/pf_skill/schema/pf_001_initial.sql - keep them in sync.
--
-- PRAGMAs (journal_mode, foreign_keys, busy_timeout) live in
-- store.py::open_db, NOT here, because journal_mode cannot be changed
-- inside a transaction.
--
-- Convention contract: docs/transactions-schema.md (v1.0).

CREATE TABLE IF NOT EXISTS pf_schema_version (
    version    INTEGER PRIMARY KEY,
    applied_at INTEGER NOT NULL
);

-- categorization_rules: regex / mcc-based rules applied by the
-- categorizer at /personal-finance:categorize time. Lower `priority`
-- wins; the first match terminates evaluation.
CREATE TABLE categorization_rules (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    priority    INTEGER NOT NULL,
    match_field TEXT NOT NULL,    -- 'mcc' | 'description' | 'counterparty'
    pattern     TEXT NOT NULL,    -- regex for description/counterparty; exact string for mcc
    category    TEXT NOT NULL,
    enabled     INTEGER NOT NULL DEFAULT 1,
    created_at  INTEGER NOT NULL,
    source      TEXT NOT NULL     -- 'seed' | 'user' | 'claude-suggested'
);

CREATE INDEX idx_rules_priority ON categorization_rules(priority, enabled);

-- tx_category: result of the categorizer pass. tx_id is a SOFT
-- reference to <bank>_transactions.id (no FK because the parent table
-- is determined by the id prefix).
CREATE TABLE tx_category (
    tx_id      TEXT PRIMARY KEY,  -- 'mono_*' | 'privat_*' | future bank prefixes
    category   TEXT NOT NULL,
    rule_id    INTEGER,            -- soft FK to categorization_rules; NULL if manual
    set_at     INTEGER NOT NULL,
    set_by     TEXT NOT NULL       -- 'rule' | 'manual' | 'claude'
);

CREATE INDEX idx_tx_category_cat ON tx_category(category);

-- category_overrides: user manually pinning a category for a specific
-- tx, bypassing rules. Higher precedence than tx_category at query
-- time via COALESCE.
CREATE TABLE category_overrides (
    tx_id     TEXT PRIMARY KEY,
    category  TEXT NOT NULL,
    note      TEXT,
    set_at    INTEGER NOT NULL
);

INSERT INTO pf_schema_version (version, applied_at)
VALUES (1, strftime('%s','now'));
