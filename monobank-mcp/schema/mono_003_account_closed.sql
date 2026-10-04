-- mono schema v3: remember accounts Monobank no longer reports.
--
-- `monobank-mcp accounts` and backfill upsert every account that
-- GET /personal/client-info returns, but nothing ever removed a row. When a
-- card is closed in the Monobank app it drops out of client-info, yet its
-- row stayed in `mono_accounts`, so every sync asked /personal/statement for
-- it, got HTTP 400 "invalid 'account'", and reported `caught_up: false`
-- forever.
--
-- `closed_at` (unix seconds) is stamped by the client-info reconciliation in
-- src/store.rs::reconcile_accounts on the first refresh that no longer lists
-- the account, and cleared again if the account reappears. NULL = live.
-- Closed rows are kept, not deleted: `mono_transactions` and
-- `mono_sync_state` reference them, and their history is still real.
-- Sync, the staleness queue and balance reconciliation skip them.

ALTER TABLE mono_accounts ADD COLUMN closed_at INTEGER;

INSERT INTO mono_schema_version (version, applied_at)
VALUES (3, strftime('%s','now'));
