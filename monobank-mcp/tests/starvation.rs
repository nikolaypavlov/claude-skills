//! Defect 3 regression: with `ORDER BY account_id` the same first accounts
//! were served on every `ensure_synced` call, so the account that sorted
//! last was unreachable no matter how many times the caller re-invoked. In
//! the incident that account was the primary spending card. Ordering by
//! `last_completed_ts` makes the queue self-rotating.

mod common;

use std::collections::HashSet;
use std::time::{Duration, Instant};

use monobank_mcp::api::MonobankApi;
use monobank_mcp::store::Store;
use monobank_mcp::sync::{AccountSyncStatus, SyncEngine};
use monobank_mcp::types::{MonoAccount, RunSource};
use monobank_mcp::util::ratelimit::RateLimiter;
use monobank_mcp::util::time::now_unix;

// Sorted ascending: `zzz_busy_card` is last under the old ordering and is
// the one that never got served.
const IDS: [&str; 4] = ["aaa_jar", "bbb_fop", "mmm_usd", "zzz_busy_card"];

async fn setup(server: &httpmock::MockServer) -> Store {
    let store = Store::open_in_memory().unwrap();
    let cursor = now_unix() - 22 * 60 * 60;
    for id in IDS {
        common::mount_statement_prefix_empty(server, id);
        store
            .upsert_account(&MonoAccount {
                id: (*id).into(),
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
        store.seed_sync_state(id, cursor).await.unwrap();
    }
    store
}

/// Every account starts equally stale, so the first pass is arbitrary; what
/// matters is that a fetched account drops to the back of the queue and the
/// unfetched ones surface. Four budget-limited runs of ~1 account each must
/// therefore touch all four accounts.
#[tokio::test]
async fn repeated_budget_limited_runs_reach_every_account() {
    let server = httpmock::MockServer::start_async().await;
    let store = setup(&server).await;

    let mut touched: HashSet<String> = HashSet::new();
    // One extra round of slack: the ordering guarantees progress, not that
    // exactly one account is served per round.
    for round in 0..6 {
        // Fresh limiter per round: a real ensure_synced call gets a limiter
        // whose last-call cursor is at worst one interval old.
        let engine = SyncEngine::__for_test(
            MonobankApi::new(server.base_url(), "test-token").unwrap(),
            store.clone(),
            RateLimiter::new(Duration::from_millis(200)),
            Some(Instant::now() + Duration::from_millis(250)),
            Duration::from_millis(200),
            0,
            RunSource::Sync,
            Duration::ZERO,
        );
        // This is the call ensure_synced makes - the ordering under test.
        let targets = store.list_account_ids_by_staleness().await.unwrap();
        assert_eq!(targets.len(), IDS.len());
        let out = engine.run(&targets).await.unwrap();
        for a in &out.per_account {
            if a.chunks_fetched > 0 {
                touched.insert(a.account_id.clone());
            }
        }
        if touched.len() == IDS.len() {
            println!("all accounts reached after {} round(s)", round + 1);
            break;
        }
    }

    let mut missing: Vec<&str> = IDS
        .iter()
        .copied()
        .filter(|id| !touched.contains(*id))
        .collect();
    missing.sort_unstable();
    assert!(
        missing.is_empty(),
        "budget-limited runs never reached {missing:?} - starvation"
    );
}

/// The ordering itself: the account with the oldest cursor is served first,
/// and fetching it sends it to the back.
#[tokio::test]
async fn staleness_order_puts_the_furthest_behind_first() {
    let server = httpmock::MockServer::start_async().await;
    let store = setup(&server).await;
    // `zzz_busy_card` sorts LAST by id but is made the stalest by cursor.
    let now = now_unix();
    store
        .rewind_sync_state("zzz_busy_card", now - 5 * 24 * 60 * 60)
        .await
        .unwrap();

    let order = store.list_account_ids_by_staleness().await.unwrap();
    assert_eq!(
        order[0], "zzz_busy_card",
        "stalest cursor must be served first, got {order:?}"
    );

    // Serve exactly that one account and confirm it rotates to the back.
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
    let out = engine.run(&["zzz_busy_card".to_string()]).await.unwrap();
    assert_eq!(out.per_account[0].status, AccountSyncStatus::Synced);

    let order = store.list_account_ids_by_staleness().await.unwrap();
    assert_eq!(
        order.last().unwrap(),
        "zzz_busy_card",
        "a fetched account must drop to the back of the queue, got {order:?}"
    );
}

/// An account discovered by `accounts` but never backfilled has no
/// `mono_sync_state` row. It sorts first, which is free: the engine seeds
/// its cursor without an API call, so it cannot consume the budget.
#[tokio::test]
async fn accounts_without_sync_state_sort_first_and_cost_nothing() {
    let server = httpmock::MockServer::start_async().await;
    let store = setup(&server).await;
    common::mount_statement_prefix_empty(&server, "new_card");
    store
        .upsert_account(&MonoAccount {
            id: "new_card".into(),
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

    let order = store.list_account_ids_by_staleness().await.unwrap();
    assert_eq!(
        order[0], "new_card",
        "unsynced account first, got {order:?}"
    );

    let engine = SyncEngine::__for_test(
        MonobankApi::new(server.base_url(), "test-token").unwrap(),
        store.clone(),
        RateLimiter::new(Duration::from_millis(200)),
        Some(Instant::now() + Duration::from_millis(250)),
        Duration::from_millis(200),
        0,
        RunSource::Sync,
        Duration::ZERO,
    );
    let out = engine.run(&order).await.unwrap();
    let seeded = &out.per_account[0];
    assert_eq!(seeded.account_id, "new_card");
    assert_eq!(seeded.status, AccountSyncStatus::Seeded);
    assert_eq!(seeded.chunks_total, 0);
    assert!(
        out.per_account.iter().any(|a| a.chunks_fetched > 0),
        "seeding must not eat the API budget"
    );
}
