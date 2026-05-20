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
