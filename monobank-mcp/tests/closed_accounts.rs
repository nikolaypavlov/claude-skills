//! Closed-account regression (0.5.0).
//!
//! A card closed in the Monobank app drops out of /personal/client-info,
//! while /personal/statement answers HTTP 400 "invalid 'account'" for it.
//! Before 0.5.0 nothing removed its `mono_accounts` row, so every sync asked
//! for it, failed, and reported `caught_up: false` forever - which made the
//! one field callers are told to trust permanently useless.
//!
//! ```text
//!   client-info lists     store before          store after reconcile
//!   ----------------      ------------          ---------------------
//!   live_card             live_card  (live)     live_card  (live)
//!                         gone_card  (live)     gone_card  (closed_at set)
//!
//!   sync queue: [live_card]        balance_checks: [live_card]
//! ```

mod common;

use std::time::Duration;

use monobank_mcp::api::MonobankApi;
use monobank_mcp::backfill::BackfillEngine;
use monobank_mcp::store::Store;
use monobank_mcp::sync::SyncEngine;
use monobank_mcp::types::{MonoAccount, RunSource};
use monobank_mcp::util::ratelimit::RateLimiter;
use monobank_mcp::util::time::now_unix;

fn account(id: &str) -> MonoAccount {
    MonoAccount {
        id: id.into(),
        iban: None,
        r#type: Some("black".into()),
        currency_code: 980,
        masked_pan: None,
        balance: Some(1_000),
        credit_limit: Some(0),
        label: None,
    }
}

async fn closed_at(store: &Store, id: &str) -> Option<i64> {
    store
        .list_accounts()
        .await
        .unwrap()
        .into_iter()
        .find(|r| r.account_id == id)
        .expect("account row must survive closing")
        .closed_at
}

#[tokio::test]
async fn reconcile_closes_accounts_missing_from_client_info() {
    let store = Store::open_in_memory().unwrap();
    store
        .reconcile_accounts(&[account("live_card"), account("gone_card")])
        .await
        .unwrap();

    let closed = store
        .reconcile_accounts(&[account("live_card")])
        .await
        .unwrap();
    assert_eq!(closed, vec!["gone_card".to_string()]);
    assert!(closed_at(&store, "gone_card").await.is_some());
    assert!(closed_at(&store, "live_card").await.is_none());

    // Already closed: a repeat refresh reports nothing new and keeps the
    // original stamp.
    let first_stamp = closed_at(&store, "gone_card").await;
    let again = store
        .reconcile_accounts(&[account("live_card")])
        .await
        .unwrap();
    assert!(
        again.is_empty(),
        "closing must be reported once, got {again:?}"
    );
    assert_eq!(closed_at(&store, "gone_card").await, first_stamp);
}

#[tokio::test]
async fn closed_account_leaves_sync_queue_and_balance_checks() {
    let store = Store::open_in_memory().unwrap();
    store
        .reconcile_accounts(&[account("live_card"), account("gone_card")])
        .await
        .unwrap();
    store
        .reconcile_accounts(&[account("live_card")])
        .await
        .unwrap();

    let queue = store.list_account_ids_by_staleness().await.unwrap();
    assert_eq!(queue, vec!["live_card".to_string()]);

    let checks = store.balance_checks().await.unwrap();
    let ids: Vec<&str> = checks.iter().map(|c| c.account_id.as_str()).collect();
    assert_eq!(ids, vec!["live_card"]);
}

#[tokio::test]
async fn account_listed_again_is_reopened() {
    let store = Store::open_in_memory().unwrap();
    store
        .reconcile_accounts(&[account("live_card"), account("card")])
        .await
        .unwrap();
    store
        .reconcile_accounts(&[account("live_card")])
        .await
        .unwrap();
    assert!(closed_at(&store, "card").await.is_some());

    let closed = store
        .reconcile_accounts(&[account("live_card"), account("card")])
        .await
        .unwrap();
    assert!(closed.is_empty());
    assert!(closed_at(&store, "card").await.is_none());
    assert!(store
        .list_account_ids_by_staleness()
        .await
        .unwrap()
        .contains(&"card".to_string()));
}

/// An empty client-info is an anomaly, not "every card was closed". Reading
/// it literally would switch off sync for the whole store at once.
#[tokio::test]
async fn empty_client_info_closes_nothing() {
    let store = Store::open_in_memory().unwrap();
    store
        .reconcile_accounts(&[account("a"), account("b")])
        .await
        .unwrap();

    let closed = store.reconcile_accounts(&[]).await.unwrap();
    assert!(closed.is_empty());
    assert_eq!(
        store.list_account_ids_by_staleness().await.unwrap().len(),
        2
    );
}

/// End to end: backfill reconciles against client-info, and the following
/// incremental sync no longer asks Monobank about the closed card, so
/// `caught_up` can become true again.
#[tokio::test]
async fn sync_after_backfill_skips_closed_card_and_catches_up() {
    let server = httpmock::MockServer::start_async().await;
    // client-info lists only FIXTURE_ACCOUNT_ID.
    common::mount_client_info(&server, &common::client_info_fixture());
    common::mount_statement_prefix_empty(&server, common::FIXTURE_ACCOUNT_ID);
    // What Monobank really answers for a closed card.
    let gone_mock = server.mock(|when, then| {
        when.method(httpmock::Method::GET)
            .path_prefix("/personal/statement/gone_card/");
        then.status(400)
            .header("content-type", "application/json")
            .body(r#"{"errorDescription":"invalid 'account'"}"#);
    });

    let store = Store::open_in_memory().unwrap();
    // The card was live once: row and cursor exist from an earlier run.
    store.upsert_account(&account("gone_card")).await.unwrap();
    store
        .seed_sync_state("gone_card", now_unix() - 2 * 24 * 60 * 60)
        .await
        .unwrap();

    let api = MonobankApi::new(server.base_url(), "test-token").unwrap();
    let limiter = RateLimiter::new(Duration::from_millis(0));
    let from = now_unix() - 24 * 60 * 60;
    BackfillEngine::new(api.clone(), store.clone(), limiter.clone(), Duration::ZERO)
        .run(vec![], Some(from))
        .await
        .unwrap();
    assert!(closed_at(&store, "gone_card").await.is_some());

    let targets = store.list_account_ids_by_staleness().await.unwrap();
    let engine = SyncEngine::__for_test(
        api,
        store.clone(),
        limiter,
        None,
        Duration::ZERO,
        0,
        RunSource::Sync,
        Duration::ZERO,
    );
    let out = engine.run(&targets).await.unwrap();
    assert!(out.caught_up, "closed card must not hold caught_up down");
    assert!(out.per_account.iter().all(|a| a.account_id != "gone_card"));
    gone_mock.assert_calls(0);
}
