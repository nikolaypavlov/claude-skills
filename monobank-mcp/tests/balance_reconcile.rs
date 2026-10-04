//! Defect 4 regression: the store already held both sides of an exact
//! integrity check and never compared them. `mono_accounts.balance_minor`
//! (from client-info) vs the running `balance_minor` on the newest stored
//! transaction. In the incident this single comparison showed a
//! -28,529.64 UAH delta on the card that was missing 7 rows, while the
//! three healthy accounts showed exactly 0.00.

mod common;

use monobank_mcp::store::{BalanceCheck, BalanceCheckVerdict, Store};
use monobank_mcp::types::{MonoAccount, MonoStatement, RunSource};

fn account(id: &str, balance: Option<i64>) -> MonoAccount {
    MonoAccount {
        id: id.into(),
        iban: None,
        r#type: Some("black".into()),
        currency_code: 980,
        masked_pan: None,
        balance,
        credit_limit: Some(0),
        label: None,
    }
}

fn tx(id: &str, ts: i64, amount: i64, balance: Option<i64>) -> MonoStatement {
    MonoStatement {
        id: id.into(),
        time: ts,
        description: "synthetic".into(),
        mcc: Some(5411),
        original_mcc: None,
        amount,
        operation_amount: amount,
        currency_code: 980,
        commission_rate: None,
        cashback_amount: None,
        balance,
        hold: Some(false),
        counter_name: None,
        counter_edrpou: None,
        counter_iban: None,
    }
}

async fn check_for(store: &Store, id: &str) -> BalanceCheck {
    store
        .balance_checks()
        .await
        .unwrap()
        .into_iter()
        .find(|c| c.account_id == id)
        .expect("account must appear in balance_checks")
}

/// The incident, reproduced in miniature: the newest stored transaction
/// leaves the card at 253,591.28 while client-info reports 225,061.64. The
/// 28,529.64 difference is the seven rows that were never fetched.
#[tokio::test]
async fn balance_disagreeing_with_newest_tx_is_flagged() {
    let store = Store::open_in_memory().unwrap();
    // Balance snapshot is stamped at "now" by upsert_account, so any
    // transaction timestamp in the past keeps the snapshot the fresher side.
    store
        .upsert_account(&account("card", Some(22_506_164)))
        .await
        .unwrap();
    let run = store.start_import_run(RunSource::Sync).await.unwrap();
    store
        .insert_statement_chunk(
            run,
            "card",
            &[
                tx("older", 1_000, -5_000, Some(25_859_128 + 5_000)),
                tx("newest", 2_000, -5_000, Some(25_359_128)),
            ],
            3_000,
            9,
        )
        .await
        .unwrap();

    let c = check_for(&store, "card").await;
    assert_eq!(c.verdict, BalanceCheckVerdict::Mismatch);
    assert_eq!(c.balance_matches_last_tx, Some(false));
    assert!(c.suspected_missing_rows);
    assert_eq!(c.delta_minor, Some(22_506_164 - 25_359_128));
    assert_eq!(c.last_tx_balance_minor, Some(25_359_128));
}

/// A healthy account: the newest row's running balance equals the snapshot.
#[tokio::test]
async fn balance_agreeing_with_newest_tx_is_clean() {
    let store = Store::open_in_memory().unwrap();
    store
        .upsert_account(&account("clean", Some(16_295)))
        .await
        .unwrap();
    let run = store.start_import_run(RunSource::Sync).await.unwrap();
    store
        .insert_statement_chunk(
            run,
            "clean",
            &[tx("only", 1_000, -700, Some(16_295))],
            2_000,
            9,
        )
        .await
        .unwrap();

    let c = check_for(&store, "clean").await;
    assert_eq!(c.verdict, BalanceCheckVerdict::Match);
    assert_eq!(c.balance_matches_last_tx, Some(true));
    assert!(!c.suspected_missing_rows);
    assert_eq!(c.delta_minor, Some(0));
}

/// `sync` never refreshes the balance snapshot - only `accounts` / backfill
/// do. A snapshot older than the newest stored row therefore cannot prove
/// anything, and must report "unknown" rather than a mismatch. This is the
/// ordinary steady state between client-info refreshes.
#[tokio::test]
async fn snapshot_older_than_newest_tx_is_unknown_not_mismatch() {
    let store = Store::open_in_memory().unwrap();
    store
        .upsert_account(&account("stale", Some(100_000)))
        .await
        .unwrap();
    let run = store.start_import_run(RunSource::Sync).await.unwrap();
    // Transaction dated far in the future relative to the snapshot that
    // upsert_account just stamped with strftime('%s','now').
    let future = monobank_mcp::util::time::now_unix() + 3_600;
    store
        .insert_statement_chunk(
            run,
            "stale",
            &[tx("later", future, -1_000, Some(99_000))],
            future + 1,
            9,
        )
        .await
        .unwrap();

    let c = check_for(&store, "stale").await;
    assert_eq!(c.verdict, BalanceCheckVerdict::SnapshotStale);
    assert_eq!(
        c.balance_matches_last_tx, None,
        "unknown must never be reported as a match"
    );
    assert!(!c.suspected_missing_rows);
    assert_eq!(c.delta_minor, None);
}

/// An account whose balance was never refreshed via client-info.
#[tokio::test]
async fn account_without_balance_snapshot_is_unknown() {
    let store = Store::open_in_memory().unwrap();
    store.upsert_account(&account("nobal", None)).await.unwrap();
    let run = store.start_import_run(RunSource::Sync).await.unwrap();
    store
        .insert_statement_chunk(run, "nobal", &[tx("t", 1_000, -1, Some(5))], 2_000, 9)
        .await
        .unwrap();

    let c = check_for(&store, "nobal").await;
    assert_eq!(c.verdict, BalanceCheckVerdict::NoBalanceSnapshot);
    assert_eq!(c.balance_matches_last_tx, None);
    assert!(!c.suspected_missing_rows);
}

/// No stored transactions, and a newest row carrying no running balance:
/// both are "not comparable", not "fine".
#[tokio::test]
async fn missing_comparands_report_unknown() {
    let store = Store::open_in_memory().unwrap();
    store
        .upsert_account(&account("empty", Some(1_000)))
        .await
        .unwrap();
    store
        .upsert_account(&account("nullbal", Some(1_000)))
        .await
        .unwrap();
    let run = store.start_import_run(RunSource::Sync).await.unwrap();
    store
        .insert_statement_chunk(run, "nullbal", &[tx("t", 1_000, -1, None)], 2_000, 9)
        .await
        .unwrap();

    assert_eq!(
        check_for(&store, "empty").await.verdict,
        BalanceCheckVerdict::NoTransactions
    );
    let c = check_for(&store, "nullbal").await;
    assert_eq!(c.verdict, BalanceCheckVerdict::NoTxBalance);
    assert_eq!(c.balance_matches_last_tx, None);
}

/// The sync engine attaches the reconciliation to its own outcome, so both
/// `ensure_synced` and CLI `sync` surface it, scoped to the accounts in the
/// run. `caught_up` stays independent: a hole inside an already-walked
/// window is not something more syncing can close.
#[tokio::test]
async fn sync_outcome_carries_balance_checks_without_gating_caught_up() {
    use std::time::Duration;

    use monobank_mcp::api::MonobankApi;
    use monobank_mcp::sync::SyncEngine;
    use monobank_mcp::util::ratelimit::RateLimiter;

    let server = httpmock::MockServer::start_async().await;
    common::mount_statement_prefix_empty(&server, "card");
    common::mount_statement_prefix_empty(&server, "other");
    let store = Store::open_in_memory().unwrap();
    store
        .upsert_account(&account("card", Some(1)))
        .await
        .unwrap();
    store
        .upsert_account(&account("other", Some(1)))
        .await
        .unwrap();
    let run = store.start_import_run(RunSource::Sync).await.unwrap();
    store
        .insert_statement_chunk(run, "card", &[tx("t", 1_000, -1, Some(999_999))], 2_000, 9)
        .await
        .unwrap();
    store
        .seed_sync_state("card", monobank_mcp::util::time::now_unix() - 600)
        .await
        .unwrap();

    let engine = SyncEngine::__for_test(
        MonobankApi::new(server.base_url(), "test-token").unwrap(),
        store.clone(),
        RateLimiter::new(Duration::ZERO),
        None,
        Duration::ZERO,
        0,
        RunSource::Sync,
        Duration::ZERO,
    );
    let out = engine.run(&["card".to_string()]).await.unwrap();

    assert!(
        out.caught_up,
        "every chunk was walked; the gap is inside an old window"
    );
    assert_eq!(
        out.accounts_with_suspected_gaps(),
        vec!["card"],
        "but the hole is still reported loudly"
    );
    assert_eq!(
        out.balance_checks.len(),
        1,
        "scoped to the accounts in this run, not the whole table"
    );
}

/// FOP-UAH is a pass-through: funds arrive from the USD account and leave
/// for the card in the same second. Picking "the newest row" by
/// `ORDER BY ts DESC, id DESC` landed on the inbound leg whenever its id
/// sorted higher, and reported a 19,771.09 hole on an account that was
/// complete. The closing balance must come out right in both id orders.
///
/// ```text
///   ts     amount      balance after
///   2_000  +1_977_109  1_980_973     same second, stored order arbitrary
///   2_000  -1_977_109      3_864
///   1_000  -2_008_575      3_864     anchor: alone in its second
/// ```
#[tokio::test]
async fn same_second_transfer_pair_is_not_a_gap() {
    for (in_id, out_id) in [("z_in", "a_out"), ("a_in", "z_out")] {
        let store = Store::open_in_memory().unwrap();
        store
            .upsert_account(&account("fop", Some(3_864)))
            .await
            .unwrap();
        let run = store.start_import_run(RunSource::Sync).await.unwrap();
        store
            .insert_statement_chunk(
                run,
                "fop",
                &[
                    tx("anchor", 1_000, -2_008_575, Some(3_864)),
                    tx(in_id, 2_000, 1_977_109, Some(1_980_973)),
                    tx(out_id, 2_000, -1_977_109, Some(3_864)),
                ],
                3_000,
                9,
            )
            .await
            .unwrap();

        let c = check_for(&store, "fop").await;
        assert_eq!(
            c.verdict,
            BalanceCheckVerdict::Match,
            "ids {in_id}/{out_id}"
        );
        assert!(!c.suspected_missing_rows);
        assert_eq!(c.last_tx_balance_minor, Some(3_864));
        assert_eq!(c.last_tx_ts, Some(2_000));
    }
}

/// The derivation must not paper over a real hole: a row missing between
/// the anchor and the same-second pair still surfaces as a mismatch.
#[tokio::test]
async fn same_second_pair_still_reports_a_real_gap() {
    let store = Store::open_in_memory().unwrap();
    // Snapshot says 3_864 - 50_000: one 50_000 spend was never stored.
    store
        .upsert_account(&account("fop", Some(3_864 - 50_000)))
        .await
        .unwrap();
    let run = store.start_import_run(RunSource::Sync).await.unwrap();
    store
        .insert_statement_chunk(
            run,
            "fop",
            &[
                tx("anchor", 1_000, -2_008_575, Some(3_864)),
                tx("in", 2_000, 1_977_109, Some(1_980_973 - 50_000)),
                tx("out", 2_000, -1_977_109, Some(3_864 - 50_000)),
            ],
            3_000,
            9,
        )
        .await
        .unwrap();

    let c = check_for(&store, "fop").await;
    assert_eq!(c.verdict, BalanceCheckVerdict::Mismatch);
    assert!(c.suspected_missing_rows);
    assert_eq!(c.delta_minor, Some(-50_000));
}

/// With no second holding a single row there is no anchor: the stored rows
/// cannot say which balance came last, so the answer is "not comparable",
/// never a false alarm and never a false match.
#[tokio::test]
async fn only_same_second_rows_is_ambiguous() {
    let store = Store::open_in_memory().unwrap();
    store
        .upsert_account(&account("fop", Some(3_864)))
        .await
        .unwrap();
    let run = store.start_import_run(RunSource::Sync).await.unwrap();
    store
        .insert_statement_chunk(
            run,
            "fop",
            &[
                tx("in", 2_000, 1_977_109, Some(1_980_973)),
                tx("out", 2_000, -1_977_109, Some(3_864)),
            ],
            3_000,
            9,
        )
        .await
        .unwrap();

    let c = check_for(&store, "fop").await;
    assert_eq!(c.verdict, BalanceCheckVerdict::AmbiguousOrder);
    assert_eq!(c.balance_matches_last_tx, None);
    assert!(!c.suspected_missing_rows);
}
