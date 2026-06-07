-- pf_003_budget_triggers.sql
--
-- Closed-budget enforcement triggers. Deferred from pf_002 because
-- the splitter then in use could not parse ``BEGIN ... END`` blocks.
-- store.py::_split_statements gained BEGIN/END tracking in the same
-- PR that lands this migration, so the triggers go in cleanly here.
--
-- The triggers refuse INSERT/UPDATE/DELETE on ``budget_line`` rows
-- whose parent ``budget`` has ``status='closed'``. The status change
-- itself (closed → active) is intentionally NOT blocked - that is
-- exactly what ``pf-budget reopen`` does. Application code can still
-- write the status flip atomically; only the ``budget_line`` rows
-- are frozen while ``status='closed'``.

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
VALUES (3, strftime('%s','now'));
