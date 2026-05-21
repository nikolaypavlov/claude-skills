-- privat_* schema, owned by privat24-skill.
-- Applied inside a single sqlite3 transaction by
-- src/privat24_import/core/store.py when privat_schema_version reports a
-- version below 1. The applier loads this file via importlib.resources
-- and executes each statement inside an explicit BEGIN/COMMIT so the
-- whole migration is atomic - sqlite3.Connection.executescript() can
-- NOT be used here because it issues an implicit COMMIT before running.
-- PRAGMA statements (journal_mode, foreign_keys, busy_timeout) are set
-- once per connection in store.py before the migration runs, NOT in
-- this file - journal_mode cannot be changed inside a transaction.
--
-- Convention contract: docs/transactions-schema.md (v1.0).

CREATE TABLE IF NOT EXISTS privat_schema_version (
    version    INTEGER PRIMARY KEY,
    applied_at INTEGER NOT NULL
);

CREATE TABLE privat_accounts (
    account_id    TEXT PRIMARY KEY,
    iban          TEXT,
    type          TEXT,
    currency_code INTEGER NOT NULL,
    masked_pan    TEXT,
    label         TEXT,
    opened_at     INTEGER
);

CREATE TABLE privat_import_runs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    source         TEXT NOT NULL DEFAULT 'xlsx',
    started_at     INTEGER NOT NULL,
    finished_at    INTEGER,
    rows_inserted  INTEGER,
    rows_skipped   INTEGER,
    error          TEXT,
    file_path      TEXT,
    file_sha256    TEXT
);

CREATE INDEX idx_privat_imports_sha ON privat_import_runs(file_sha256);

CREATE TABLE privat_transactions (
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
    raw_json          TEXT NOT NULL,
    imported_at       INTEGER NOT NULL,
    import_run_id     INTEGER NOT NULL,
    FOREIGN KEY (account_id) REFERENCES privat_accounts(account_id),
    FOREIGN KEY (import_run_id) REFERENCES privat_import_runs(id)
);

CREATE INDEX idx_privat_tx_ts ON privat_transactions(ts);
CREATE INDEX idx_privat_tx_account ON privat_transactions(account_id, ts);

INSERT INTO privat_schema_version (version, applied_at)
VALUES (1, strftime('%s','now'));
