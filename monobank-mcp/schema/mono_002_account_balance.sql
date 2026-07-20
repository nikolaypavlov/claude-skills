-- mono schema v2: persist per-account balance and credit limit.
--
-- `balance` and `creditLimit` come from GET /personal/client-info (fetched
-- by `monobank-mcp accounts` and backfill, NOT by incremental sync - see
-- src/store.rs::upsert_account). Storing them lets downstream compute real
-- funds without inferring a balance from the transaction tail, which is
-- ambiguous for same-timestamp transfer pairs (pass-through accounts).
--
-- Monobank's `balance` INCLUDES the credit line, so:
--     real_funds = balance_minor - credit_limit_minor
-- A `balance_minor` below `credit_limit_minor` means the account is drawing
-- on credit (debt).
--
-- All three columns are nullable: accounts discovered but never refreshed
-- via client-info, and rows migrated from v1, carry NULLs until the next
-- `accounts`/backfill run populates them. `balance_synced_at` (unix seconds)
-- lets callers show an "as of" and judge staleness.

ALTER TABLE mono_accounts ADD COLUMN balance_minor INTEGER;
ALTER TABLE mono_accounts ADD COLUMN credit_limit_minor INTEGER;
ALTER TABLE mono_accounts ADD COLUMN balance_synced_at INTEGER;

INSERT INTO mono_schema_version (version, applied_at)
VALUES (2, strftime('%s','now'));
