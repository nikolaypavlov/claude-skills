//! Verify that the SyncEngine's deadline budget produces a partial result
//! and that the partial result can be resumed by a follow-up call.

mod common;

use std::time::{Duration, Instant};

use monobank_mcp::api::MonobankApi;
use monobank_mcp::store::Store;
use monobank_mcp::sync::SyncEngine;
use monobank_mcp::types::{MonoAccount, RunSource};
use monobank_mcp::util::ratelimit::RateLimiter;
use monobank_mcp::util::time::{now_unix, CHUNK_SECONDS};

#[tokio::test]
async fn deadline_produces_partial_then_resumes() {
    let server = httpmock::MockServer::start_async().await;
    common::mount_statement_prefix_empty(&server, common::FIXTURE_ACCOUNT_ID);

    let api = MonobankApi::new(server.base_url(), "test-token").unwrap();
    let store = Store::open_in_memory().unwrap();
    store
        .upsert_account(&MonoAccount {
            id: common::FIXTURE_ACCOUNT_ID.into(),
            iban: None,
            r#type: Some("black".into()),
            currency_code: 980,
            masked_pan: None,
            balance: None,
            label: None,
        })
        .await
        .unwrap();
    // Three-chunk job: cursor is 93 days behind now.
    let now = now_unix();
    let start = now - 3 * CHUNK_SECONDS;
    store
        .seed_sync_state(common::FIXTURE_ACCOUNT_ID, start)
        .await
        .unwrap();

    // Interval = 0 so we don't actually sleep, but deadline = now means
    // `time_exhausted()` returns true before the first chunk runs.
    let engine = SyncEngine::__for_test(
        api,
        store.clone(),
        RateLimiter::new(Duration::from_millis(0)),
        Some(Instant::now() - Duration::from_secs(1)),
        Duration::from_secs(60),
        0,
        RunSource::Sync,
        Duration::ZERO,
    );
    let out = engine
        .run(&[common::FIXTURE_ACCOUNT_ID.into()])
        .await
        .unwrap();
    assert!(out.partial(), "should report partial when budget is gone");
    assert_eq!(out.per_account[0].remaining_chunks, 3);

    // Resume: no deadline, interval = 0 -> all chunks finish.
    let engine = SyncEngine::__for_test(
        MonobankApi::new(server.base_url(), "test-token").unwrap(),
        store.clone(),
        RateLimiter::new(Duration::from_millis(0)),
        None,
        Duration::from_millis(0),
        0,
        RunSource::Sync,
        Duration::ZERO,
    );
    let out2 = engine
        .run(&[common::FIXTURE_ACCOUNT_ID.into()])
        .await
        .unwrap();
    assert!(!out2.partial(), "resume should clear partial");
    assert_eq!(out2.per_account[0].remaining_chunks, 0);
    let cursor = store
        .get_sync_state(common::FIXTURE_ACCOUNT_ID)
        .await
        .unwrap()
        .unwrap();
    assert!(cursor.last_completed_ts >= now - 60);
}

// When `sync` runs against an account that has never been backfilled,
// the engine seeds the cursor at "now" and returns a clean outcome instead
// of erroring. Subsequent syncs then operate normally. The historical
// window is intentionally NOT pulled - users who want history run
// `backfill --from <date>` explicitly.
#[tokio::test]
async fn sync_auto_seeds_missing_state_to_now() {
    let server = httpmock::MockServer::start_async().await;
    // Mount the statement endpoint just in case the engine still calls it -
    // returning empty proves at most that the call happened with `from=now`.
    common::mount_statement_prefix_empty(&server, common::FIXTURE_ACCOUNT_ID);

    let api = MonobankApi::new(server.base_url(), "test-token").unwrap();
    let store = Store::open_in_memory().unwrap();
    store
        .upsert_account(&MonoAccount {
            id: common::FIXTURE_ACCOUNT_ID.into(),
            iban: None,
            r#type: Some("black".into()),
            currency_code: 980,
            masked_pan: None,
            balance: None,
            label: None,
        })
        .await
        .unwrap();
    // No seed_sync_state - this is the "fresh account" scenario.
    assert!(store
        .get_sync_state(common::FIXTURE_ACCOUNT_ID)
        .await
        .unwrap()
        .is_none());

    let engine = SyncEngine::__for_test(
        api,
        store.clone(),
        RateLimiter::new(Duration::from_millis(0)),
        None,
        Duration::from_millis(0),
        0,
        RunSource::Sync,
        Duration::ZERO,
    );
    let now_before = now_unix();
    let out = engine
        .run(&[common::FIXTURE_ACCOUNT_ID.into()])
        .await
        .unwrap();

    let acc = &out.per_account[0];
    assert!(
        acc.error.is_none(),
        "fresh account should not surface an error; got {acc:?}"
    );
    assert_eq!(acc.rows_added, 0);
    assert_eq!(acc.remaining_chunks, 0);
    assert!(acc.last_completed_ts >= now_before);

    // The sync_state row must exist after the run so subsequent syncs
    // don't repeat the auto-seed branch.
    let cursor = store
        .get_sync_state(common::FIXTURE_ACCOUNT_ID)
        .await
        .unwrap()
        .expect("sync_state row should be persisted");
    assert!(cursor.last_completed_ts >= now_before);
}
