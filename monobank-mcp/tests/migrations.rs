//! Verify a fresh, empty DB file is migrated correctly, that the version
//! row lands at EXPECTED_MONO_SCHEMA_VERSION, and that repeating the
//! migration does not duplicate rows.

use monobank_mcp::migrations::{ensure_mono_schema, EXPECTED_MONO_SCHEMA_VERSION};
use rusqlite::Connection;
use tempfile::tempdir;

fn open(path: &std::path::Path) -> Connection {
    let conn = Connection::open(path).unwrap();
    conn.execute_batch(
        "PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON; PRAGMA busy_timeout=5000;",
    )
    .unwrap();
    conn
}

#[test]
fn fresh_file_db_applies_schema() {
    let dir = tempdir().unwrap();
    let db = dir.path().join("data.db");
    {
        let mut conn = open(&db);
        ensure_mono_schema(&mut conn).unwrap();
        let v: i64 = conn
            .query_row("SELECT MAX(version) FROM mono_schema_version", [], |r| {
                r.get(0)
            })
            .unwrap();
        assert_eq!(v, EXPECTED_MONO_SCHEMA_VERSION);
    }
    // Re-open the file in a new process-style connection: schema persists.
    let conn = open(&db);
    let tables: Vec<String> = conn
        .prepare(
            "SELECT name FROM sqlite_master WHERE type='table' \
             AND name LIKE 'mono_%' ORDER BY name",
        )
        .unwrap()
        .query_map([], |r| r.get::<_, String>(0))
        .unwrap()
        .collect::<Result<_, _>>()
        .unwrap();
    assert_eq!(
        tables,
        vec![
            "mono_accounts".to_string(),
            "mono_import_runs".into(),
            "mono_schema_version".into(),
            "mono_sync_state".into(),
            "mono_transactions".into(),
        ]
    );
}

#[test]
fn rerun_does_not_duplicate_version_row() {
    let dir = tempdir().unwrap();
    let db = dir.path().join("data.db");
    let mut conn = open(&db);
    ensure_mono_schema(&mut conn).unwrap();
    ensure_mono_schema(&mut conn).unwrap();
    ensure_mono_schema(&mut conn).unwrap();
    // One row per applied migration; reruns must not re-insert any.
    let n: i64 = conn
        .query_row("SELECT COUNT(*) FROM mono_schema_version", [], |r| r.get(0))
        .unwrap();
    assert_eq!(n, EXPECTED_MONO_SCHEMA_VERSION);
}

#[test]
fn v2_adds_account_balance_columns() {
    let dir = tempdir().unwrap();
    let db = dir.path().join("data.db");
    let mut conn = open(&db);
    ensure_mono_schema(&mut conn).unwrap();
    let cols: Vec<String> = conn
        .prepare("SELECT name FROM pragma_table_info('mono_accounts') ORDER BY name")
        .unwrap()
        .query_map([], |r| r.get::<_, String>(0))
        .unwrap()
        .collect::<Result<_, _>>()
        .unwrap();
    for expected in ["balance_minor", "credit_limit_minor", "balance_synced_at"] {
        assert!(
            cols.iter().any(|c| c == expected),
            "mono_accounts missing column {expected}; has {cols:?}"
        );
    }
}
