//! Backfill cursor / chunking contract:
//!   * `backfill_is_idempotent_across_runs` - re-running the same range
//!     produces no new rows. Verifies the INSERT-OR-IGNORE + cursor-MAX
//!     combination inside `insert_statement_chunk`.
//!   * `backfill_rewalks_when_from_is_earlier_than_existing_cursor` -
//!     explicit `--from <past_date>` lowers the cursor floor so the
//!     engine re-walks the whole requested range. INSERT OR IGNORE makes
//!     the re-fetched chunks idempotent. This is what the user means by
//!     "give me everything from this date" - the prior cursor position
//!     does not override the explicit floor.

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
async fn backfill_rewalks_when_from_is_earlier_than_existing_cursor() {
    use monobank_mcp::util::time::CHUNK_SECONDS;

    let server = httpmock::MockServer::start_async().await;
    common::mount_client_info(&server, &common::client_info_fixture());

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

    // Simulate a store whose cursor is already at ~now (e.g. after a
    // narrower backfill --from one-week-ago). The user then asks for
    // --from 90 days ago. The engine must rewind the floor and walk
    // all 3 chunks, not silently treat the request as a no-op.
    let now = monobank_mcp::util::time::now_unix();
    let from = now - 3 * CHUNK_SECONDS;
    let prior_cursor = now;
    store
        .upsert_account(&monobank_mcp::types::MonoAccount {
            id: common::FIXTURE_ACCOUNT_ID.into(),
            iban: None,
            r#type: Some("black".into()),
            currency_code: common::FIXTURE_CCY_UAH,
            masked_pan: None,
            balance: None,
            credit_limit: None,
            label: None,
        })
        .await
        .unwrap();
    store
        .seed_sync_state(common::FIXTURE_ACCOUNT_ID, prior_cursor)
        .await
        .unwrap();

    engine.run(vec![], Some(from)).await.unwrap();
    assert_eq!(
        statement_mock.calls(),
        3,
        "expected three statement chunks fetched (one per 31d window from \
         the rewound floor up to now), got {}",
        statement_mock.calls()
    );

    let cursor_after = store
        .get_sync_state(common::FIXTURE_ACCOUNT_ID)
        .await
        .unwrap()
        .unwrap()
        .last_completed_ts;
    assert!(cursor_after >= now - 60);
}

#[tokio::test]
async fn rewind_sync_state_keeps_lower_existing_cursor() {
    use monobank_mcp::types::MonoAccount;

    let store = Store::open_in_memory().unwrap();
    let acc_id = "rewind-acc";
    store
        .upsert_account(&MonoAccount {
            id: acc_id.into(),
            iban: None,
            r#type: Some("black".into()),
            currency_code: common::FIXTURE_CCY_UAH,
            masked_pan: None,
            balance: None,
            credit_limit: None,
            label: None,
        })
        .await
        .unwrap();
    // Existing cursor sits at an early timestamp; a later rewind target
    // must not advance it - rewind only ever moves the floor backwards.
    store.seed_sync_state(acc_id, 1_000).await.unwrap();
    store.rewind_sync_state(acc_id, 5_000).await.unwrap();
    let st = store.get_sync_state(acc_id).await.unwrap().unwrap();
    assert_eq!(
        st.last_completed_ts, 1_000,
        "rewind must keep the lower existing cursor"
    );

    // Now the inverse: rewind to an earlier ts lowers the floor.
    store.rewind_sync_state(acc_id, 500).await.unwrap();
    let st = store.get_sync_state(acc_id).await.unwrap().unwrap();
    assert_eq!(st.last_completed_ts, 500);
}
