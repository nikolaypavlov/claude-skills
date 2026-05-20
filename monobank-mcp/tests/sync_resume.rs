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
    let engine = SyncEngine {
        api,
        store: store.clone(),
        limiter: RateLimiter::new(Duration::from_millis(0)),
        deadline: Some(Instant::now() - Duration::from_secs(1)),
        interval: Duration::from_secs(60),
        freshness_skip_seconds: 0,
        source: RunSource::Sync,
    };
    let out = engine
        .run(&[common::FIXTURE_ACCOUNT_ID.into()])
        .await
        .unwrap();
    assert!(out.partial(), "should report partial when budget is gone");
    assert_eq!(out.per_account[0].remaining_chunks, 3);

    // Resume: no deadline, interval = 0 -> all chunks finish.
    let engine = SyncEngine {
        api: MonobankApi::new(server.base_url(), "test-token").unwrap(),
        store: store.clone(),
        limiter: RateLimiter::new(Duration::from_millis(0)),
        deadline: None,
        interval: Duration::from_millis(0),
        freshness_skip_seconds: 0,
        source: RunSource::Sync,
    };
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
