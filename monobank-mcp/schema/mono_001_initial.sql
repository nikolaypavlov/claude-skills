-- mono_* schema, owned by monobank-mcp.
-- This file is applied verbatim by src/migrations.rs when the
-- mono_schema_version table reports a version below 1.
--
-- Convention contract: docs/transactions-schema.md (v1.0).

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS mono_schema_version (
    version    INTEGER PRIMARY KEY,
    applied_at INTEGER NOT NULL
);

CREATE TABLE mono_accounts (
    account_id    TEXT PRIMARY KEY,
    iban          TEXT,
    type          TEXT,
    currency_code INTEGER NOT NULL,
    masked_pan    TEXT,
    label         TEXT,
    opened_at     INTEGER
);

CREATE TABLE mono_import_runs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    source         TEXT NOT NULL,
    started_at     INTEGER NOT NULL,
    finished_at    INTEGER,
    rows_inserted  INTEGER,
    rows_skipped   INTEGER,
    error          TEXT
);

CREATE TABLE mono_transactions (
    id                TEXT PRIMARY KEY,
    account_id        TEXT NOT NULL,
    ts                INTEGER NOT NULL,
    amount_minor      INTEGER NOT NULL,
    currency_code     INTEGER NOT NULL,
    op_amount_minor   INTEGER,
    op_currency_code  INTEGER,
    mcc               INTEGER,
    description       TEXT,
    counterparty      TEXT,
    balance_minor     INTEGER,
    cashback_minor    INTEGER,
    raw_json          TEXT NOT NULL,
    imported_at       INTEGER NOT NULL,
    import_run_id     INTEGER NOT NULL,
    FOREIGN KEY (account_id) REFERENCES mono_accounts(account_id),
    FOREIGN KEY (import_run_id) REFERENCES mono_import_runs(id)
);

CREATE INDEX idx_mono_tx_ts ON mono_transactions(ts);
CREATE INDEX idx_mono_tx_account ON mono_transactions(account_id, ts);
CREATE INDEX idx_mono_tx_mcc ON mono_transactions(mcc);

CREATE TABLE mono_sync_state (
    account_id          TEXT PRIMARY KEY,
    last_completed_ts   INTEGER NOT NULL,
    last_sync_at        INTEGER NOT NULL,
    FOREIGN KEY (account_id) REFERENCES mono_accounts(account_id)
);

INSERT INTO mono_schema_version (version, applied_at)
VALUES (1, strftime('%s','now'));
