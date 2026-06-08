-- pf_004_budget_draft_edit.sql
--
-- Edit log per draft budget. Powers the `pf-budget plan undo` flow
-- so the user can say "стоп, поверни школу" mid-conversation and the
-- CLI reverses the last applied change.
--
-- Lifecycle:
--   - INSERT on every add-line / update-line / remove-line that runs
--     against a draft budget
--   - DELETE rows for a budget when its draft is committed (the log
--     is per-session, not durable history)
--   - CASCADE delete when the budget itself is deleted (cancel path)
--
-- op values:
--   'add'    - new line was inserted; payload_after is the new row,
--              payload_before is NULL
--   'update' - line was modified; payload_before holds the prior shape,
--              payload_after the new shape
--   'remove' - line was deleted; payload_before holds the deleted shape,
--              payload_after is NULL
--
-- payload columns store JSON dicts with at minimum
-- {line_id, category, currency_code, kind, amount_minor, note}.

CREATE TABLE budget_draft_edit (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    budget_id       INTEGER NOT NULL REFERENCES budget(id) ON DELETE CASCADE,
    op              TEXT NOT NULL,
    payload_before  TEXT,
    payload_after   TEXT,
    applied_at      INTEGER NOT NULL,
    CHECK (op IN ('add', 'update', 'remove'))
);

CREATE INDEX idx_budget_draft_edit_budget ON budget_draft_edit(budget_id, id);

INSERT INTO pf_schema_version (version, applied_at)
VALUES (4, strftime('%s','now'));
