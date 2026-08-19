//! Regression tests for the 0.3.0 "caught_up while rows are missing" defect.
//!
//! The incident: `ensure_synced` returned `caught_up: true, rows_added: 0`
//! for eight accounts while the primary card was missing 22 hours of real
//! spending. Two independent bugs combined:
//!   1. `caught_up` was computed from cursor lag alone, with a 24h tolerance,
//!      so a never-fetched account inside that window looked current.
//!   2. Nothing in the response separated "fetched, found nothing" from
//!      "never fetched".
//!
//! A third bug (fixed ordering starving the busiest account) is what kept
//! the gap from self-healing across re-invocations; see `starvation.rs`.

mod common;

use std::time::{Duration, Instant};

use monobank_mcp::api::MonobankApi;
use monobank_mcp::store::Store;
use monobank_mcp::sync::{AccountSyncStatus, SyncEngine};
use monobank_mcp::types::{MonoAccount, RunSource};
use monobank_mcp::util::ratelimit::RateLimiter;
use monobank_mcp::util::time::now_unix;

const HOURS_22: i64 = 22 * 60 * 60;

async fn seed_account(store: &Store, id: &str) {
    store
        .upsert_account(&MonoAccount {
            id: id.into(),
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
}

/// Engine with a deadline already in the past: `time_exhausted()` is true
/// before the first chunk, so no account is ever contacted.
fn starved_engine(api: MonobankApi, store: Store) -> SyncEngine {
    SyncEngine::__for_test(
        api,
        store,
        RateLimiter::new(Duration::ZERO),
        Some(Instant::now() - Duration::from_secs(1)),
        Duration::from_secs(60),
        0,
        RunSource::Sync,
        Duration::ZERO,
    )
}

fn unbounded_engine(api: MonobankApi, store: Store) -> SyncEngine {
    SyncEngine::__for_test(
        api,
        store,
        RateLimiter::new(Duration::ZERO),
        None,
        Duration::ZERO,
        0,
        RunSource::Sync,
        Duration::ZERO,
    )
}

/// Defect 2: a 22-hour gap sat comfortably under the old 24h
/// `CAUGHT_UP_GAP_SECONDS`, so an account with a whole unfetched day of
/// spending reported `caught_up: true`. One unfetched chunk is now enough
/// to make `caught_up` false regardless of how small the gap is.
#[tokio::test]
async fn sub_threshold_gap_with_unfetched_chunk_is_not_caught_up() {
    let server = httpmock::MockServer::start_async().await;
    common::mount_statement_prefix_empty(&server, common::FIXTURE_ACCOUNT_ID);
    let api = MonobankApi::new(server.base_url(), "test-token").unwrap();
    let store = Store::open_in_memory().unwrap();
    seed_account(&store, common::FIXTURE_ACCOUNT_ID).await;
    // Exactly the shape of the incident: cursor 22h behind -> one chunk.
    store
        .seed_sync_state(common::FIXTURE_ACCOUNT_ID, now_unix() - HOURS_22)
        .await
        .unwrap();

    let out = starved_engine(api, store.clone())
        .run(&[common::FIXTURE_ACCOUNT_ID.into()])
        .await
        .unwrap();

    let acc = &out.per_account[0];
    assert_eq!(acc.remaining_chunks, 1);
    assert!(
        acc.gap_seconds < 24 * 60 * 60,
        "precondition: the gap must be inside the retired 24h tolerance, got {}",
        acc.gap_seconds
    );
    assert!(
        !out.caught_up,
        "an unfetched chunk means an unchecked window, however small the gap"
    );
}

/// Defect 1: the budget affords fewer API calls than there are accounts.
/// `caught_up` must be false AND the response must let a caller point at
/// which accounts were never contacted - `rows_added: 0` cannot do that.
#[tokio::test]
async fn budget_shorter_than_account_list_marks_untouched_accounts() {
    let server = httpmock::MockServer::start_async().await;
    let ids = ["acc_a", "acc_b", "acc_c"];
    for id in ids {
        common::mount_statement_prefix_empty(&server, id);
    }
    let api = MonobankApi::new(server.base_url(), "test-token").unwrap();
    let store = Store::open_in_memory().unwrap();
    let cursor = now_unix() - HOURS_22;
    for id in ids {
        seed_account(&store, id).await;
        store.seed_sync_state(id, cursor).await.unwrap();
    }

    // Production shape (61s limiter vs a 90s budget) scaled down to
    // milliseconds so the test does not sleep for minutes. The limiter really
    // sleeps 300ms between calls and the deadline is 400ms out, so by the
    // third account `Instant::now() + interval > deadline` is unavoidably
    // true: at most two accounts can be reached, whatever the machine speed.
    let engine = SyncEngine::__for_test(
        api,
        store.clone(),
        RateLimiter::new(Duration::from_millis(300)),
        Some(Instant::now() + Duration::from_millis(400)),
        Duration::from_millis(300),
        0,
        RunSource::Sync,
        Duration::ZERO,
    );
    let targets: Vec<String> = ids.iter().map(|s| (*s).to_string()).collect();
    let out = engine.run(&targets).await.unwrap();

    assert!(!out.caught_up, "not every account was walked");
    let untouched: Vec<&str> = out
        .per_account
        .iter()
        .filter(|a| a.status == AccountSyncStatus::Unattempted)
        .map(|a| a.account_id.as_str())
        .collect();
    assert!(
        !untouched.is_empty(),
        "at least one account must be reported as never contacted; got {:?}",
        out.per_account
    );
    for a in &out.per_account {
        assert_eq!(a.chunks_total, a.chunks_fetched + a.remaining_chunks);
        if a.status == AccountSyncStatus::Unattempted {
            // The whole point: identifiable as untouched from the response
            // alone, without comparing against any external state.
            assert_eq!(a.chunks_fetched, 0);
            assert!(a.chunks_total > 0);
            assert_eq!(a.rows_added, 0, "the ambiguous field, still zero");
        }
    }
}

/// The legitimate case `caught_up` exists for: the chunk WAS fetched and
/// Monobank genuinely returned nothing. This must stay true - the fix must
/// not degrade into "caught_up = !partial and never true in practice".
#[tokio::test]
async fn fetched_but_empty_window_is_caught_up() {
    let server = httpmock::MockServer::start_async().await;
    common::mount_statement_prefix_empty(&server, common::FIXTURE_ACCOUNT_ID);
    let api = MonobankApi::new(server.base_url(), "test-token").unwrap();
    let store = Store::open_in_memory().unwrap();
    seed_account(&store, common::FIXTURE_ACCOUNT_ID).await;
    store
        .seed_sync_state(common::FIXTURE_ACCOUNT_ID, now_unix() - HOURS_22)
        .await
        .unwrap();

    let out = unbounded_engine(api, store.clone())
        .run(&[common::FIXTURE_ACCOUNT_ID.into()])
        .await
        .unwrap();

    let acc = &out.per_account[0];
    assert_eq!(acc.status, AccountSyncStatus::Synced);
    assert_eq!(acc.rows_added, 0, "the window really was empty");
    assert_eq!(acc.chunks_fetched, 1, "but we did look");
    assert_eq!(acc.remaining_chunks, 0);
    assert!(out.caught_up);
}

/// The other legitimate no-API-call path: the freshness skip. This is what
/// makes the retired 24h tolerance unnecessary - a cursor trailing by
/// seconds after a complete sync reports `remaining_chunks: 0` honestly and
/// still yields `caught_up: true` without any gap fudge.
#[tokio::test]
async fn freshness_skip_is_caught_up_without_a_gap_tolerance() {
    let server = httpmock::MockServer::start_async().await;
    common::mount_statement_prefix_empty(&server, common::FIXTURE_ACCOUNT_ID);
    let api = MonobankApi::new(server.base_url(), "test-token").unwrap();
    let store = Store::open_in_memory().unwrap();
    seed_account(&store, common::FIXTURE_ACCOUNT_ID).await;
    // Cursor 10s behind, synced just now -> inside a 300s freshness window.
    store
        .seed_sync_state(common::FIXTURE_ACCOUNT_ID, now_unix() - 10)
        .await
        .unwrap();

    let engine = SyncEngine::__for_test(
        api,
        store.clone(),
        RateLimiter::new(Duration::ZERO),
        None,
        Duration::ZERO,
        300,
        RunSource::Sync,
        Duration::ZERO,
    );
    let out = engine
        .run(&[common::FIXTURE_ACCOUNT_ID.into()])
        .await
        .unwrap();

    let acc = &out.per_account[0];
    assert_eq!(acc.status, AccountSyncStatus::SkippedFresh);
    assert_eq!(acc.remaining_chunks, 0);
    assert!(out.caught_up);
    assert!(out.skipped_all);
}

/// A failed chunk keeps `caught_up` false and is reported as `Failed`, not
/// as a silent zero-row account.
#[tokio::test]
async fn failed_chunk_is_not_caught_up() {
    let server = httpmock::MockServer::start_async().await;
    server.mock(|when, then| {
        when.method(httpmock::Method::GET).path_prefix(format!(
            "/personal/statement/{}/",
            common::FIXTURE_ACCOUNT_ID
        ));
        then.status(403).body("forbidden");
    });
    let api = MonobankApi::new(server.base_url(), "test-token").unwrap();
    let store = Store::open_in_memory().unwrap();
    seed_account(&store, common::FIXTURE_ACCOUNT_ID).await;
    store
        .seed_sync_state(common::FIXTURE_ACCOUNT_ID, now_unix() - HOURS_22)
        .await
        .unwrap();

    let out = unbounded_engine(api, store.clone())
        .run(&[common::FIXTURE_ACCOUNT_ID.into()])
        .await
        .unwrap();

    let acc = &out.per_account[0];
    assert_eq!(acc.status, AccountSyncStatus::Failed);
    assert!(acc.error.is_some());
    assert_eq!(acc.chunks_fetched, 0);
    assert!(!out.caught_up);
}

/// Wire contract: 0.4.0 only ADDS fields. A consumer written against 0.3.0
/// must still find every key it used to read, with the same types.
#[tokio::test]
async fn per_account_json_keeps_legacy_fields_and_adds_new_ones() {
    let server = httpmock::MockServer::start_async().await;
    common::mount_statement_prefix_empty(&server, common::FIXTURE_ACCOUNT_ID);
    let api = MonobankApi::new(server.base_url(), "test-token").unwrap();
    let store = Store::open_in_memory().unwrap();
    seed_account(&store, common::FIXTURE_ACCOUNT_ID).await;
    store
        .seed_sync_state(common::FIXTURE_ACCOUNT_ID, now_unix() - HOURS_22)
        .await
        .unwrap();

    let out = unbounded_engine(api, store.clone())
        .run(&[common::FIXTURE_ACCOUNT_ID.into()])
        .await
        .unwrap();
    let v = serde_json::to_value(&out.per_account[0]).unwrap();

    for legacy in [
        "account_id",
        "rows_added",
        "rows_skipped",
        "last_completed_ts",
        "remaining_chunks",
        "gap_seconds",
        "error",
    ] {
        assert!(
            v.get(legacy).is_some(),
            "0.3.0 field `{legacy}` disappeared"
        );
    }
    for added in ["status", "chunks_total", "chunks_fetched"] {
        assert!(v.get(added).is_some(), "0.4.0 field `{added}` missing");
    }
    assert_eq!(v["status"], "synced", "status serializes as snake_case");
}
