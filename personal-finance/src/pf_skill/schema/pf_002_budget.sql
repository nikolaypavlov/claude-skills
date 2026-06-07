-- pf_002_budget.sql
--
-- Adds the four budget-feature tables:
--   * category_registry    - explicit "this category exists" contract
--   * budget               - one row per (period, currency_code)
--   * budget_line          - the plan rows
--   * budget_import_run    - audit log of pf-budget imports
--
-- And triggers that prevent edits to ``budget_line`` rows whose
-- parent budget has been closed. The status lifecycle itself is
-- enforced at the application layer (the CLI checks before
-- delete-and-replace); the triggers are belt-and-braces against
-- direct DB edits.
--
-- See ``budget-design.md`` for the design contract this migration
-- lands. PR1 of the budget feature only adds the schema and the
-- category_registry CLI; the actual ``pf-budget import / show /
-- diff`` commands ride in later PRs but require these tables to
-- exist.

CREATE TABLE category_registry (
    category     TEXT PRIMARY KEY,
    declared_at  INTEGER NOT NULL,
    declared_via TEXT NOT NULL,
    note         TEXT,
    CHECK (declared_via IN ('budget-import', 'cli', 'rules'))
);

CREATE TABLE budget (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    period         TEXT NOT NULL,
    currency_code  INTEGER NOT NULL,
    status         TEXT NOT NULL DEFAULT 'draft',
    created_at     INTEGER NOT NULL,
    imported_from  TEXT,
    UNIQUE (period, currency_code),
    CHECK (period GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]'),
    CHECK (status IN ('draft', 'active', 'closed'))
);

CREATE TABLE budget_line (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    budget_id    INTEGER NOT NULL REFERENCES budget(id) ON DELETE CASCADE,
    category     TEXT NOT NULL,
    amount_minor INTEGER NOT NULL,
    kind         TEXT NOT NULL,
    note         TEXT,
    CHECK (kind IN ('baseline', 'one_time', 'income'))
);

CREATE INDEX idx_budget_line_budget ON budget_line(budget_id);
CREATE INDEX idx_budget_line_category ON budget_line(category);

CREATE TABLE budget_import_run (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    source         TEXT NOT NULL,
    period         TEXT NOT NULL,
    imported_at    INTEGER NOT NULL,
    lines_added    INTEGER NOT NULL,
    lines_replaced INTEGER NOT NULL,
    new_categories TEXT
);

-- NOTE: closed-budget enforcement triggers (BEFORE UPDATE / DELETE /
-- INSERT on budget_line where parent budget.status = 'closed') are
-- intentionally NOT in this migration. They need BEGIN...END blocks
-- which the current ``_split_statements`` in ``store.py`` does not
-- handle, and PR1 has no ``pf-budget close`` command to produce
-- closed budgets in the first place. The triggers ride with
-- ``pf-budget close / reopen`` (PR6 in budget-design.md), at which
-- point the splitter also gets upgraded to walk BEGIN/END depth.

INSERT INTO pf_schema_version (version, applied_at)
VALUES (2, strftime('%s','now'));
