//! Two flavours of "resume" coverage:
//!   * `backfill_is_idempotent_across_runs` - re-running the same range
//!     produces no new rows and the cursor stays put. Verifies the
//!     INSERT-OR-IGNORE + cursor-MAX combination.
//!   * `backfill_resume_skips_already_completed_chunks` - simulates a
//!     prior partial run by seeding `last_completed_ts` partway into a
//!     multi-chunk range, then asserts the engine only fetches the
//!     remaining chunks. This catches a regression where `seed_sync_state`
//!     would overwrite a higher cursor instead of using INSERT OR IGNORE.

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
    let engine = BackfillEngine::new(api, store.clone(), limiter, Duration::from_millis(0));

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

#[tokio::test]
async fn backfill_resume_skips_already_completed_chunks() {
    use monobank_mcp::util::time::CHUNK_SECONDS;

    let server = httpmock::MockServer::start_async().await;
    common::mount_client_info(&server, &common::client_info_fixture());

    // Track how many statement requests hit the server.
    let statement_mock = server.mock(|when, then| {
        when.method(httpmock::Method::GET).path_prefix(format!(
            "/personal/statement/{}/",
            common::FIXTURE_ACCOUNT_ID
        ));
        then.status(200)
            .header("content-type", "application/json")
            .body("[]");
    });

    let api = MonobankApi::new(server.base_url(), "test-token").unwrap();
    let store = Store::open_in_memory().unwrap();
    let limiter = RateLimiter::new(Duration::from_millis(0));
    let engine = BackfillEngine::new(api, store.clone(), limiter, Duration::from_millis(0));

    // Simulate "two chunks already done": 90 days back is 3 chunks; cursor
    // sits at +60 days from start = end-of-chunk-2.
    let now = monobank_mcp::util::time::now_unix();
    let from = now - 3 * CHUNK_SECONDS;
    let prior_cursor = from + 2 * CHUNK_SECONDS;
    // Account row + sync_state row must exist BEFORE backfill, so the
    // engine's seed_sync_state (INSERT OR IGNORE) is a no-op.
    store
        .upsert_account(&monobank_mcp::types::MonoAccount {
            id: common::FIXTURE_ACCOUNT_ID.into(),
            iban: None,
            r#type: Some("black".into()),
            currency_code: common::FIXTURE_CCY_UAH,
            masked_pan: None,
            balance: None,
            label: None,
        })
        .await
        .unwrap();
    store
        .seed_sync_state(common::FIXTURE_ACCOUNT_ID, prior_cursor)
        .await
        .unwrap();

    // Run backfill - it should only fetch the remaining 1 chunk
    // (prior_cursor .. now), NOT all 3.
    engine.run(vec![], Some(from)).await.unwrap();
    assert_eq!(
        statement_mock.calls(),
        1,
        "expected one statement chunk fetched (the unfinished one), got {}",
        statement_mock.calls()
    );

    let cursor_after = store
        .get_sync_state(common::FIXTURE_ACCOUNT_ID)
        .await
        .unwrap()
        .unwrap()
        .last_completed_ts;
    assert!(cursor_after >= now - 60);
    assert!(cursor_after > prior_cursor);
}
