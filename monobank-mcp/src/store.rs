//! Local SQLite store for `mono_*` tables.
//!
//! Owns `mono_accounts`, `mono_transactions`, `mono_sync_state`,
//! `mono_import_runs`, `mono_schema_version`. Does NOT touch tables owned
//! by other plugins (`privat_*`, `pf_*`). See docs/transactions-schema.md.
//!
//! Concurrency:
//!   - WAL is enabled defensively on every open. Safe to re-run.
//!   - We use a single Mutex-guarded connection per `Store` instance for
//!     write paths. Reads also go through the same connection - SQLite
//!     handles read concurrency itself via WAL but the rusqlite Connection
//!     is `!Sync`.
//!
//! Atomicity:
//!   - `insert_statement_chunk` wraps INSERTs into `mono_transactions` and
//!     the `mono_sync_state.last_completed_ts` UPSERT in one transaction so
//!     a kill mid-chunk never leaves the cursor ahead of the data.

use std::path::Path;
use std::sync::Arc;

use anyhow::{Context, Result};
use rusqlite::{params, Connection};
use serde_json::json;
use tokio::sync::Mutex;

use crate::migrations::ensure_mono_schema;
use crate::types::{MonoAccount, MonoStatement, RunSource};

/// Result of a single chunk insert.
#[derive(Debug, Clone, Copy, Default, serde::Serialize)]
pub struct ChunkInsertOutcome {
    pub rows_inserted: u64,
    pub rows_skipped: u64,
}

#[derive(Clone)]
pub struct Store {
    conn: Arc<Mutex<Connection>>,
}

impl Store {
    /// Open `path`, apply PRAGMA defaults, run mono migrations. Idempotent.
    pub fn open(path: &Path) -> Result<Self> {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent).ok();
        }
        let conn =
            Connection::open(path).with_context(|| format!("open sqlite at {}", path.display()))?;
        Self::init(conn)
    }

    pub fn open_in_memory() -> Result<Self> {
        let conn = Connection::open_in_memory().context("open in-memory sqlite")?;
        Self::init(conn)
    }

    fn init(conn: Connection) -> Result<Self> {
        conn.execute_batch(
            "PRAGMA journal_mode=WAL;
             PRAGMA foreign_keys=ON;
             PRAGMA busy_timeout=5000;",
        )
        .context("apply PRAGMA defaults")?;
        ensure_mono_schema(&conn)?;
        Ok(Self {
            conn: Arc::new(Mutex::new(conn)),
        })
    }

    pub async fn upsert_account(&self, acc: &MonoAccount) -> Result<()> {
        let conn = self.conn.lock().await;
        let masked = acc
            .masked_pan
            .as_ref()
            .map(|v| v.join(","))
            .unwrap_or_default();
        conn.execute(
            "INSERT INTO mono_accounts \
                 (account_id, iban, type, currency_code, masked_pan, label, opened_at) \
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, NULL) \
             ON CONFLICT(account_id) DO UPDATE SET \
                 iban = excluded.iban, \
                 type = excluded.type, \
                 currency_code = excluded.currency_code, \
                 masked_pan = excluded.masked_pan, \
                 label = COALESCE(excluded.label, mono_accounts.label)",
            params![
                acc.id,
                acc.iban,
                acc.r#type,
                acc.currency_code,
                if masked.is_empty() {
                    None
                } else {
                    Some(masked)
                },
                acc.label,
            ],
        )?;
        Ok(())
    }

    pub async fn list_accounts(&self) -> Result<Vec<AccountRow>> {
        let conn = self.conn.lock().await;
        let mut stmt = conn.prepare(
            "SELECT account_id, iban, type, currency_code, masked_pan, label, opened_at \
             FROM mono_accounts ORDER BY account_id",
        )?;
        let rows = stmt
            .query_map([], |row| {
                Ok(AccountRow {
                    account_id: row.get(0)?,
                    iban: row.get(1)?,
                    r#type: row.get(2)?,
                    currency_code: row.get(3)?,
                    masked_pan: row.get(4)?,
                    label: row.get(5)?,
                    opened_at: row.get(6)?,
                })
            })?
            .collect::<Result<Vec<_>, _>>()?;
        Ok(rows)
    }

    /// Open a new import_run. Returns the AUTOINCREMENT id.
    pub async fn start_import_run(&self, source: RunSource) -> Result<i64> {
        let conn = self.conn.lock().await;
        conn.execute(
            "INSERT INTO mono_import_runs (source, started_at) VALUES (?1, strftime('%s','now'))",
            params![source.as_str()],
        )?;
        Ok(conn.last_insert_rowid())
    }

    pub async fn finish_import_run(
        &self,
        id: i64,
        rows_inserted: u64,
        rows_skipped: u64,
        error: Option<String>,
    ) -> Result<()> {
        let conn = self.conn.lock().await;
        conn.execute(
            "UPDATE mono_import_runs \
             SET finished_at = strftime('%s','now'), rows_inserted = ?2, \
                 rows_skipped = ?3, error = ?4 \
             WHERE id = ?1",
            params![id, rows_inserted as i64, rows_skipped as i64, error],
        )?;
        Ok(())
    }

    /// Insert a chunk of statement rows and bump the sync cursor for the
    /// account in a single SQLite transaction. Existing rows are skipped
    /// (`INSERT OR IGNORE`). The cursor (`last_completed_ts`) jumps to the
    /// upper bound of the window passed by the caller, NOT to the max
    /// timestamp inside `items` - this guarantees no data loss when a chunk
    /// happens to be empty.
    #[allow(clippy::too_many_arguments)]
    pub async fn insert_statement_chunk(
        &self,
        import_run_id: i64,
        account_id: &str,
        items: &[MonoStatement],
        window_end_ts: i64,
        imported_at: i64,
    ) -> Result<ChunkInsertOutcome> {
        let mut conn = self.conn.lock().await;
        let tx = conn.transaction()?;
        let mut rows_inserted: u64 = 0;
        let mut rows_skipped: u64 = 0;
        {
            let mut stmt = tx.prepare(
                "INSERT OR IGNORE INTO mono_transactions \
                 (id, account_id, ts, amount_minor, currency_code, op_amount_minor, \
                  op_currency_code, mcc, description, counterparty, balance_minor, \
                  cashback_minor, raw_json, imported_at, import_run_id) \
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15)",
            )?;
            for st in items {
                let id = format!("mono_{}", st.id);
                // op_amount/op_currency are only meaningful when the original
                // currency differs from the account currency.
                let op_amount = if st.currency_code == 0 || st.operation_amount == st.amount {
                    None
                } else {
                    Some(st.operation_amount)
                };
                let op_currency = if st.currency_code == 0 {
                    None
                } else {
                    Some(st.currency_code)
                };
                let counterparty = best_counterparty(st);
                let raw_json = serde_json::to_string(st)
                    .unwrap_or_else(|_| json!({"id": st.id, "fallback": true}).to_string());
                let changed = stmt.execute(params![
                    id,
                    account_id,
                    st.time,
                    st.amount,
                    st.currency_code,
                    op_amount,
                    op_currency,
                    st.mcc,
                    st.description,
                    counterparty,
                    st.balance,
                    st.cashback_amount,
                    raw_json,
                    imported_at,
                    import_run_id,
                ])?;
                if changed == 0 {
                    rows_skipped += 1;
                } else {
                    rows_inserted += 1;
                }
            }
        }
        tx.execute(
            "INSERT INTO mono_sync_state (account_id, last_completed_ts, last_sync_at) \
                 VALUES (?1, ?2, strftime('%s','now')) \
             ON CONFLICT(account_id) DO UPDATE SET \
                 last_completed_ts = MAX(mono_sync_state.last_completed_ts, excluded.last_completed_ts), \
                 last_sync_at = excluded.last_sync_at",
            params![account_id, window_end_ts],
        )?;
        tx.commit()?;
        Ok(ChunkInsertOutcome {
            rows_inserted,
            rows_skipped,
        })
    }

    pub async fn get_sync_state(&self, account_id: &str) -> Result<Option<SyncStateRow>> {
        let conn = self.conn.lock().await;
        let mut stmt = conn.prepare(
            "SELECT account_id, last_completed_ts, last_sync_at \
             FROM mono_sync_state WHERE account_id = ?1",
        )?;
        let mut rows = stmt.query(params![account_id])?;
        if let Some(row) = rows.next()? {
            return Ok(Some(SyncStateRow {
                account_id: row.get(0)?,
                last_completed_ts: row.get(1)?,
                last_sync_at: row.get(2)?,
            }));
        }
        Ok(None)
    }

    pub async fn list_sync_state(&self) -> Result<Vec<SyncStateRow>> {
        let conn = self.conn.lock().await;
        let mut stmt = conn.prepare(
            "SELECT account_id, last_completed_ts, last_sync_at FROM mono_sync_state \
             ORDER BY account_id",
        )?;
        let rows = stmt
            .query_map([], |row| {
                Ok(SyncStateRow {
                    account_id: row.get(0)?,
                    last_completed_ts: row.get(1)?,
                    last_sync_at: row.get(2)?,
                })
            })?
            .collect::<Result<Vec<_>, _>>()?;
        Ok(rows)
    }

    /// Initialise `last_completed_ts` for an account when no row exists yet
    /// (e.g. backfill --from). Does nothing if already present.
    pub async fn seed_sync_state(&self, account_id: &str, last_completed_ts: i64) -> Result<()> {
        let conn = self.conn.lock().await;
        conn.execute(
            "INSERT OR IGNORE INTO mono_sync_state (account_id, last_completed_ts, last_sync_at) \
             VALUES (?1, ?2, strftime('%s','now'))",
            params![account_id, last_completed_ts],
        )?;
        Ok(())
    }

    pub async fn count_transactions(&self) -> Result<i64> {
        let conn = self.conn.lock().await;
        let n: i64 = conn.query_row("SELECT COUNT(*) FROM mono_transactions", [], |r| r.get(0))?;
        Ok(n)
    }
}

/// Pick the best human counterparty label from a statement row.
fn best_counterparty(st: &MonoStatement) -> Option<String> {
    if let Some(n) = st.counter_name.as_ref() {
        if !n.is_empty() {
            return Some(n.clone());
        }
    }
    None
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct AccountRow {
    pub account_id: String,
    pub iban: Option<String>,
    pub r#type: Option<String>,
    pub currency_code: i64,
    pub masked_pan: Option<String>,
    pub label: Option<String>,
    pub opened_at: Option<i64>,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct SyncStateRow {
    pub account_id: String,
    pub last_completed_ts: i64,
    pub last_sync_at: i64,
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::MonoStatement;

    fn mk_st(id: &str, ts: i64, amount: i64) -> MonoStatement {
        MonoStatement {
            id: id.into(),
            time: ts,
            description: "test".into(),
            mcc: Some(5411),
            original_mcc: None,
            amount,
            operation_amount: amount,
            currency_code: 980,
            commission_rate: None,
            cashback_amount: None,
            balance: Some(100_000),
            hold: Some(false),
            counter_name: None,
            counter_edrpou: None,
            counter_iban: None,
        }
    }

    #[tokio::test]
    async fn insert_chunk_then_repeat_is_idempotent() {
        let s = Store::open_in_memory().unwrap();
        s.upsert_account(&MonoAccount {
            id: "acc1".into(),
            iban: None,
            r#type: Some("card".into()),
            currency_code: 980,
            masked_pan: None,
            balance: None,
            label: None,
        })
        .await
        .unwrap();
        let run_id = s.start_import_run(RunSource::Backfill).await.unwrap();
        let items = vec![mk_st("a", 1000, -500), mk_st("b", 1100, -2000)];
        let r1 = s
            .insert_statement_chunk(run_id, "acc1", &items, 1200, 9999)
            .await
            .unwrap();
        assert_eq!(r1.rows_inserted, 2);
        assert_eq!(r1.rows_skipped, 0);
        let r2 = s
            .insert_statement_chunk(run_id, "acc1", &items, 1200, 9999)
            .await
            .unwrap();
        assert_eq!(r2.rows_inserted, 0);
        assert_eq!(r2.rows_skipped, 2);
        assert_eq!(s.count_transactions().await.unwrap(), 2);
        let st = s.get_sync_state("acc1").await.unwrap().unwrap();
        assert_eq!(st.last_completed_ts, 1200);
    }

    #[tokio::test]
    async fn cursor_does_not_go_backwards() {
        let s = Store::open_in_memory().unwrap();
        s.upsert_account(&MonoAccount {
            id: "acc1".into(),
            iban: None,
            r#type: Some("card".into()),
            currency_code: 980,
            masked_pan: None,
            balance: None,
            label: None,
        })
        .await
        .unwrap();
        let run_id = s.start_import_run(RunSource::Sync).await.unwrap();
        s.insert_statement_chunk(run_id, "acc1", &[], 2000, 1)
            .await
            .unwrap();
        s.insert_statement_chunk(run_id, "acc1", &[], 1000, 1)
            .await
            .unwrap();
        let st = s.get_sync_state("acc1").await.unwrap().unwrap();
        assert_eq!(st.last_completed_ts, 2000);
    }
}
