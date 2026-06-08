-- pf_005_budget_unique_per_status.sql
--
-- Loosen budget's UNIQUE constraint so a draft and an active budget
-- for the same (period, currency_code) can coexist during a planning
-- session. ``commit_draft`` replaces the active atomically by
-- deleting the old active and flipping the draft's status in the
-- same transaction; both rows must be valid up to that point.
--
-- Old:  UNIQUE (period, currency_code)
-- New:  UNIQUE (period, currency_code, status)
--
-- SQLite doesn't let us alter a constraint in place; the table is
-- rebuilt. The closed-budget triggers from pf_003 reference
-- ``budget`` in their WHEN clauses, so we drop them before the
-- table swap and recreate them afterwards.
--
-- ``defer_foreign_keys`` defers the FK check from
-- ``budget_line.budget_id`` until COMMIT, so the temporary
-- drop-and-rename within the migration transaction is safe.

PRAGMA defer_foreign_keys = ON;

DROP TRIGGER IF EXISTS budget_line_no_insert_when_closed;
DROP TRIGGER IF EXISTS budget_line_no_update_when_closed;
DROP TRIGGER IF EXISTS budget_line_no_delete_when_closed;

CREATE TABLE budget_new (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    period         TEXT NOT NULL,
    currency_code  INTEGER NOT NULL,
    status         TEXT NOT NULL DEFAULT 'draft',
    created_at     INTEGER NOT NULL,
    imported_from  TEXT,
    UNIQUE (period, currency_code, status),
    CHECK (period GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]'),
    CHECK (status IN ('draft', 'active', 'closed'))
);

INSERT INTO budget_new (id, period, currency_code, status, created_at, imported_from)
SELECT id, period, currency_code, status, created_at, imported_from FROM budget;

DROP TABLE budget;
ALTER TABLE budget_new RENAME TO budget;

CREATE TRIGGER budget_line_no_insert_when_closed
BEFORE INSERT ON budget_line
WHEN (SELECT status FROM budget WHERE id = NEW.budget_id) = 'closed'
BEGIN
    SELECT RAISE(ABORT, 'budget_line: parent budget is closed, reopen first');
END;

CREATE TRIGGER budget_line_no_update_when_closed
BEFORE UPDATE ON budget_line
WHEN (SELECT status FROM budget WHERE id = OLD.budget_id) = 'closed'
BEGIN
    SELECT RAISE(ABORT, 'budget_line: parent budget is closed, reopen first');
END;

CREATE TRIGGER budget_line_no_delete_when_closed
BEFORE DELETE ON budget_line
WHEN (SELECT status FROM budget WHERE id = OLD.budget_id) = 'closed'
BEGIN
    SELECT RAISE(ABORT, 'budget_line: parent budget is closed, reopen first');
END;

INSERT INTO pf_schema_version (version, applied_at)
VALUES (5, strftime('%s','now'));
