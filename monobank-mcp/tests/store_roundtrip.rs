//! Store-level round-trip tests on an in-memory rusqlite connection.
//! Complements the unit tests inside `store.rs`.

mod common;

use monobank_mcp::store::Store;
use monobank_mcp::types::{MonoAccount, MonoStatement, RunSource};

fn synth_account() -> MonoAccount {
    MonoAccount {
        id: common::FIXTURE_ACCOUNT_ID.into(),
        iban: Some("UA000000000000000000000000001".into()),
        r#type: Some("black".into()),
        currency_code: common::FIXTURE_CCY_UAH,
        masked_pan: Some(vec!["537541******1234".into()]),
        balance: Some(1_234_567),
        label: None,
    }
}

fn synth_statements(start_ts: i64, n: usize) -> Vec<MonoStatement> {
    (0..n)
        .map(|i| MonoStatement {
            id: format!("stmt_{:08}_{}", start_ts, i),
            time: start_ts + (i as i64) * 600,
            description: format!("Synthetic merchant #{}", i),
            mcc: Some(5411),
            original_mcc: Some(5411),
            amount: -25_000 - (i as i64) * 100,
            operation_amount: -25_000 - (i as i64) * 100,
            currency_code: 980,
            commission_rate: Some(0),
            cashback_amount: Some(0),
            balance: Some(1_234_567 - (i as i64) * 25_000),
            hold: Some(false),
            counter_name: None,
            counter_edrpou: None,
            counter_iban: None,
        })
        .collect()
}

#[tokio::test]
async fn fresh_open_creates_schema() {
    let s = Store::open_in_memory().unwrap();
    assert_eq!(s.count_transactions().await.unwrap(), 0);
    assert!(s.list_accounts().await.unwrap().is_empty());
}

#[tokio::test]
async fn insert_then_query_roundtrip() {
    let s = Store::open_in_memory().unwrap();
    s.upsert_account(&synth_account()).await.unwrap();
    let run_id = s.start_import_run(RunSource::Backfill).await.unwrap();
    let items = synth_statements(1_000_000, 4);
    let r = s
        .insert_statement_chunk(
            run_id,
            common::FIXTURE_ACCOUNT_ID,
            &items,
            1_001_000,
            9_999_999,
        )
        .await
        .unwrap();
    assert_eq!(r.rows_inserted, 4);
    assert_eq!(s.count_transactions().await.unwrap(), 4);
    s.finish_import_run(run_id, r.rows_inserted, r.rows_skipped, None)
        .await
        .unwrap();
    let accounts = s.list_accounts().await.unwrap();
    assert_eq!(accounts.len(), 1);
    assert_eq!(accounts[0].account_id, common::FIXTURE_ACCOUNT_ID);
}

#[tokio::test]
async fn duplicate_insert_is_idempotent() {
    let s = Store::open_in_memory().unwrap();
    s.upsert_account(&synth_account()).await.unwrap();
    let run = s.start_import_run(RunSource::Sync).await.unwrap();
    let items = synth_statements(2_000_000, 2);
    s.insert_statement_chunk(run, common::FIXTURE_ACCOUNT_ID, &items, 2_002_000, 9)
        .await
        .unwrap();
    let r2 = s
        .insert_statement_chunk(run, common::FIXTURE_ACCOUNT_ID, &items, 2_002_000, 9)
        .await
        .unwrap();
    assert_eq!(r2.rows_inserted, 0);
    assert_eq!(r2.rows_skipped, 2);
    assert_eq!(s.count_transactions().await.unwrap(), 2);
}
