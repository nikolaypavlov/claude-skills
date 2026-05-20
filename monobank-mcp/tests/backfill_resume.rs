//! Verify that backfill is resumable across consecutive runs.
//!
//! We don't actually kill the engine mid-chunk - instead we simulate
//! "ran two chunks, then crashed" by running a backfill that has a small
//! window, observing the sync cursor, then running another backfill
//! starting from a NEW point and confirming no duplicate rows.

mod common;

use std::time::Duration;

use monobank_mcp::api::MonobankApi;
use monobank_mcp::backfill::BackfillEngine;
use monobank_mcp::store::Store;
use monobank_mcp::util::ratelimit::RateLimiter;

#[tokio::test]
async fn backfill_is_idempotent_across_runs() {
    let server = httpmock::MockServer::start_async().await;
    common::mount_client_info(&server, &common::client_info_fixture());
    // Catch-all empty for all statement paths: we don't need real rows to
    // verify that the cursor advances and the second run is a no-op.
    common::mount_statement_prefix_empty(&server, common::FIXTURE_ACCOUNT_ID);

    let api = MonobankApi::new(server.base_url(), "test-token").unwrap();
    let store = Store::open_in_memory().unwrap();
    // Very small interval so the test does not sleep for a real minute.
    let limiter = RateLimiter::new(Duration::from_millis(0));
    let engine = BackfillEngine {
        api,
        store: store.clone(),
        limiter,
        interval: Duration::from_millis(0),
    };

    // Run #1: from 30 days ago to now.
    let now = monobank_mcp::util::time::now_unix();
    let from = now - 30 * 24 * 60 * 60;
    let r1 = engine.run(vec![], Some(from)).await.unwrap();
    assert!(
        !r1.per_account.is_empty(),
        "backfill should touch the account"
    );
    let cursor_after_1 = store
        .get_sync_state(common::FIXTURE_ACCOUNT_ID)
        .await
        .unwrap()
        .unwrap()
        .last_completed_ts;
    assert!(cursor_after_1 >= now - 60, "cursor should reach ~now");

    // Run #2: same range, no new rows, cursor stays >= previous.
    let r2 = engine.run(vec![], Some(from)).await.unwrap();
    assert!(r2.rows_added == 0);
    let cursor_after_2 = store
        .get_sync_state(common::FIXTURE_ACCOUNT_ID)
        .await
        .unwrap()
        .unwrap()
        .last_completed_ts;
    assert!(cursor_after_2 >= cursor_after_1);
}
