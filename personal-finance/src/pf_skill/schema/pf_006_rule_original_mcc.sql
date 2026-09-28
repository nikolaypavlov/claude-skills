-- pf_006_rule_original_mcc.sql
--
-- Optional second condition on a categorization rule: the merchant's
-- ORIGINAL MCC as the bank received it, before any bank-side remap.
--
-- Why: Monobank rewrites ``mcc`` for some merchants to a single
-- umbrella code (e.g. every Rozetka charge lands as 5262), so a
-- marketplace purchase and that marketplace's own paid subscription
-- look identical in ``description`` / ``counterparty`` / ``mcc``. The
-- only field that still tells them apart is ``originalMcc`` inside
-- ``raw_json`` (5399 goods vs 8999 services).
--
-- Semantics: NULL = no constraint (every pre-existing rule). A non-NULL
-- value is ANDed with the rule's match_field/pattern test:
--
--   match_field/pattern  AND  (original_mcc IS NULL OR tx.original_mcc = original_mcc)
--
-- Banks whose payload has no originalMcc yield NULL on the tx side, so
-- a constrained rule never matches them.

ALTER TABLE categorization_rules ADD COLUMN original_mcc INTEGER;

INSERT INTO pf_schema_version (version, applied_at)
VALUES (6, strftime('%s','now'));
