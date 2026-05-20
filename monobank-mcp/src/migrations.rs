//! Per-plugin schema migrations.
//!
//! Each numbered SQL file under `schema/` is embedded via `include_str!` so
//! the binary is self-contained at runtime. We track the highest applied
//! version in `mono_schema_version` and apply pending files in order.
//!
//! Atomicity:
//!   - `mono_schema_version` is created via CREATE TABLE IF NOT EXISTS so
//!     the first run never short-circuits on a missing tracker.
//!   - Each pending migration runs inside an explicit rusqlite transaction:
//!     `BEGIN` -> `execute_batch(<file>)` -> `COMMIT`. A crash mid-apply
//!     rolls back automatically and leaves the schema at the previous
//!     version, so a partially-applied schema bump is impossible.
//!   - PRAGMAs that cannot be changed inside a transaction (e.g.
//!     `journal_mode`) are set once on the connection in `Store::init()`
//!     BEFORE migrations run.

use anyhow::{Context, Result};
use rusqlite::Connection;

/// Schema files in apply order. New migrations go at the end.
const MIGRATIONS: &[(i64, &str)] = &[(1, include_str!("../schema/mono_001_initial.sql"))];

pub const EXPECTED_MONO_SCHEMA_VERSION: i64 = 1;

pub fn ensure_mono_schema(conn: &mut Connection) -> Result<()> {
    conn.execute_batch(
        "CREATE TABLE IF NOT EXISTS mono_schema_version (
             version    INTEGER PRIMARY KEY,
             applied_at INTEGER NOT NULL
         );",
    )
    .context("create mono_schema_version")?;

    let applied: i64 = conn
        .query_row(
            "SELECT COALESCE(MAX(version), 0) FROM mono_schema_version",
            [],
            |row| row.get(0),
        )
        .context("read max(mono_schema_version)")?;

    for (version, sql) in MIGRATIONS {
        if *version <= applied {
            continue;
        }
        let tx = conn
            .transaction()
            .with_context(|| format!("begin mono migration v{version}"))?;
        tx.execute_batch(sql)
            .with_context(|| format!("apply mono migration v{version}"))?;
        tx.commit()
            .with_context(|| format!("commit mono migration v{version}"))?;
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn in_memory() -> Connection {
        Connection::open_in_memory().unwrap()
    }

    #[test]
    fn fresh_db_applies_initial_migration() {
        let mut conn = in_memory();
        ensure_mono_schema(&mut conn).unwrap();
        let v: i64 = conn
            .query_row("SELECT MAX(version) FROM mono_schema_version", [], |r| {
                r.get(0)
            })
            .unwrap();
        assert_eq!(v, EXPECTED_MONO_SCHEMA_VERSION);
        let table_count: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN \
                 ('mono_accounts','mono_transactions','mono_sync_state','mono_import_runs','mono_schema_version')",
                [],
                |r| r.get(0),
            )
            .unwrap();
        assert_eq!(table_count, 5);
    }

    #[test]
    fn rerun_is_idempotent() {
        let mut conn = in_memory();
        ensure_mono_schema(&mut conn).unwrap();
        ensure_mono_schema(&mut conn).unwrap();
        let rows: i64 = conn
            .query_row("SELECT COUNT(*) FROM mono_schema_version", [], |r| r.get(0))
            .unwrap();
        assert_eq!(rows, 1);
    }
}
