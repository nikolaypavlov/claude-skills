//! End-to-end API tests against a local httpmock server.

mod common;

use monobank_mcp::api::MonobankApi;

#[tokio::test]
async fn client_info_returns_synthetic_account() {
    let server = httpmock::MockServer::start_async().await;
    let body = common::client_info_fixture();
    common::mount_client_info(&server, &body);
    let api = MonobankApi::new(server.base_url(), "test-token").unwrap();
    let info = api.client_info().await.unwrap();
    assert_eq!(info.accounts.len(), 1);
    assert_eq!(info.accounts[0].id, common::FIXTURE_ACCOUNT_ID);
    assert_eq!(info.accounts[0].currency_code, common::FIXTURE_CCY_UAH);
}

#[tokio::test]
async fn statement_parses_synthetic_rows() {
    let server = httpmock::MockServer::start_async().await;
    let body = common::statement_fixture(100_000, 3);
    common::mount_statement_range(&server, common::FIXTURE_ACCOUNT_ID, 50_000, 200_000, &body);
    let api = MonobankApi::new(server.base_url(), "test-token").unwrap();
    let items = api
        .statement(common::FIXTURE_ACCOUNT_ID, 50_000, Some(200_000))
        .await
        .unwrap();
    assert_eq!(items.len(), 3);
    assert_eq!(items[0].time, 100_000);
    assert_eq!(items[0].amount, -25_000);
    assert_eq!(items[1].time, 100_600);
}

#[tokio::test]
async fn statement_401_maps_to_auth_failed() {
    let server = httpmock::MockServer::start_async().await;
    server.mock(|when, then| {
        when.method(httpmock::Method::GET)
            .path_prefix("/personal/statement/");
        then.status(401)
            .body(r#"{"errorDescription":"Unknown 'X-Token'"}"#);
    });
    let api = MonobankApi::new(server.base_url(), "bad").unwrap();
    let err = api.statement("acc", 0, Some(1)).await.unwrap_err();
    let s = format!("{err}");
    assert!(s.contains("auth failed") || s.contains("401"), "got: {s}");
}

#[tokio::test]
async fn statement_429_maps_to_rate_limited() {
    let server = httpmock::MockServer::start_async().await;
    server.mock(|when, then| {
        when.method(httpmock::Method::GET)
            .path_prefix("/personal/statement/");
        then.status(429)
            .body(r#"{"errorDescription":"Too Many Requests"}"#);
    });
    let api = MonobankApi::new(server.base_url(), "x").unwrap();
    let err = api.statement("acc", 0, Some(1)).await.unwrap_err();
    let s = format!("{err}");
    assert!(s.contains("rate limited") || s.contains("429"), "got: {s}");
}

// Drives `SyncEngine::pull_and_store` through its retry loop: every call
// returns 429, so after 3 attempts the engine surfaces the error in
// `AccountSyncOutcome.error` and stops the loop. We override
// `retry_backoff` to ZERO so the test finishes in milliseconds; production
// uses `DEFAULT_RETRY_BACKOFF` (90s).
#[tokio::test]
async fn sync_engine_retries_rate_limited_three_times_then_gives_up() {
    use std::time::Duration;

    use monobank_mcp::store::Store;
    use monobank_mcp::sync::SyncEngine;
    use monobank_mcp::types::{MonoAccount, RunSource};
    use monobank_mcp::util::ratelimit::RateLimiter;
    use monobank_mcp::util::time::{now_unix, CHUNK_SECONDS};

    let server = httpmock::MockServer::start_async().await;
    let m_429 = server.mock(|when, then| {
        when.method(httpmock::Method::GET)
            .path_prefix("/personal/statement/");
        then.status(429).body("{}");
    });

    let api = MonobankApi::new(server.base_url(), "test-token").unwrap();
    let store = Store::open_in_memory().unwrap();
    store
        .upsert_account(&MonoAccount {
            id: "acc1".into(),
            iban: None,
            r#type: Some("black".into()),
            currency_code: 980,
            masked_pan: None,
            balance: None,
            credit_limit: None,
            label: None,
        })
        .await
        .unwrap();
    let now = now_unix();
    // Single-chunk window so the engine attempts exactly one chunk and
    // we can count attempts via the mock hits.
    store
        .seed_sync_state("acc1", now - CHUNK_SECONDS / 2)
        .await
        .unwrap();

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
    let outcome = engine.run(&["acc1".into()]).await.unwrap();
    assert_eq!(
        m_429.calls(),
        3,
        "expected exactly 3 attempts, got {}",
        m_429.calls()
    );
    let acc = &outcome.per_account[0];
    assert!(
        acc.error.is_some(),
        "per-account error must surface after retries exhaust; got {acc:?}"
    );
    assert_eq!(acc.remaining_chunks, 1, "chunk stays unfinished");
}
